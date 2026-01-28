#!/usr/bin/env bash


# --- support 'curl ... | bash' without breaking TUI --------------------------
# If this script is being read from a PIPE (curl | bash), slurp it to a temp file
# and re-exec from that file. After that, it's safe to reattach to /dev/tty.
if [ -p /dev/stdin ]; then
  tmp="$(mktemp -t openrag.XXXXXX)"
  # Read the entire piped script into the temp file
  cat > "$tmp"
  chmod +x "$tmp"
  exec bash "$tmp" "$@"
fi

# Now we are running from a real file, not stdin. It is safe to reattach.
# (Only if not already attached to a TTY)
if [ ! -t 0 ] || [ ! -t 1 ] || [ ! -t 2 ]; then
  if [ -e /dev/tty ]; then
    exec </dev/tty >/dev/tty 2>&1
  else
    echo "This installer needs an interactive terminal. Try: bash <(curl -fsSL ...)" >&2
    exit 1
  fi
fi


set -euo pipefail

say() { printf "%s\n" "$*" >&2; }
hr() { say "----------------------------------------"; }

ask_yes_no() {
  local prompt="${1:-Continue?} [Y/n] "
  read -r -p "$prompt" ans || true
  case "${ans:-Y}" in [Yy]|[Yy][Ee][Ss]|"") return 0 ;; *) return 1 ;; esac
}

# --- Platform detection ------------------------------------------------------
uname_s="$(uname -s 2>/dev/null || echo unknown)"
is_wsl=false
if [ -f /proc/version ]; then grep -qiE 'microsoft|wsl' /proc/version && is_wsl=true || true; fi

case "$uname_s" in
  Darwin) PLATFORM="macOS" ;;
  Linux)  PLATFORM="$($is_wsl && echo WSL || echo Linux)" ;;
  CYGWIN*|MINGW*|MSYS*) PLATFORM="Windows" ;;
  *) PLATFORM="Unknown" ;;
esac

if [ "$PLATFORM" = "Windows" ]; then
  say ">>> Native Windows shell detected. Please run this inside WSL (Ubuntu, etc.)."
  exit 1
fi

# --- Minimal sudo (used only when necessary) --------------------------------
SUDO="sudo"; $SUDO -n true >/dev/null 2>&1 || SUDO="sudo"  # may prompt later only if needed

# --- PATH probe for common bins (no sudo) -----------------------------------
ensure_path_has_common_bins() {
  local add=()
  [ -d /opt/homebrew/bin ] && add+=("/opt/homebrew/bin")
  [ -d /usr/local/bin ] && add+=("/usr/local/bin")
  [ -d "/Applications/Docker.app/Contents/Resources/bin" ] && add+=("/Applications/Docker.app/Contents/Resources/bin")
  [ -d "$HOME/.docker/cli-plugins" ] && add+=("$HOME/.docker/cli-plugins")
  if [ ${#add[@]} -gt 0 ]; then
    for p in "${add[@]}"; do case ":$PATH:" in *":$p:"*) ;; *) PATH="$p:$PATH" ;; esac; done
  fi
  export PATH
}
ensure_path_has_common_bins

# --- Helpers ----------------------------------------------------------------
has_cmd() { command -v "$1" >/dev/null 2>&1; }
docker_cli_path() { command -v docker 2>/dev/null || true; }
podman_cli_path() { command -v podman 2>/dev/null || true; }

docker_daemon_ready() { docker info >/dev/null 2>&1; }         # no sudo; fails if socket perms/daemon issue
compose_v2_ready() { docker compose version >/dev/null 2>&1; }
compose_v1_ready() { command -v docker-compose >/dev/null 2>&1; }
podman_ready() { podman info >/dev/null 2>&1; }                # macOS may need podman machine

docker_is_podman() {
  # True if `docker` is Podman (podman-docker shim or alias)
  if ! has_cmd docker; then return 1; fi

  # 1) Text outputs
  local out=""
  out+="$(docker --version 2>&1 || true)\n"
  out+="$(docker -v 2>&1 || true)\n"
  out+="$(docker help 2>&1 | head -n 2 || true)\n"
  if printf "%b" "$out" | grep -qiE '\bpodman\b'; then
    return 0
  fi

  # 2) Symlink target / alternatives
  local p t
  p="$(command -v docker)"
  if has_cmd readlink; then
    t="$(readlink -f "$p" 2>/dev/null || readlink "$p" 2>/dev/null || echo "$p")"
    printf "%s" "$t" | grep -qi 'podman' && return 0
  fi
  if [ -L /etc/alternatives/docker ]; then
    t="$(readlink -f /etc/alternatives/docker 2>/dev/null || true)"
    printf "%s" "$t" | grep -qi 'podman' && return 0
  fi

  # 3) Fallback: package id (rpm/dpkg), best effort (ignore errors)
  if has_cmd rpm; then
    rpm -qf "$p" 2>/dev/null | grep -qi 'podman' && return 0
  fi
  if has_cmd dpkg-query; then
    dpkg-query -S "$p" 2>/dev/null | grep -qi 'podman' && return 0
  fi

  return 1
}

# --- Homebrew install (macOS only, idempotent) -----------------------------
install_homebrew_if_missing() {
  [ "$PLATFORM" != "macOS" ] && return 0
  if has_cmd brew; then
    say ">>> Homebrew present: $(brew --version 2>/dev/null | head -1 || echo ok)"
    return 0
  fi
  say ">>> Homebrew not found."
  if ! ask_yes_no "Install Homebrew now?"; then return 1; fi
  if ! has_cmd curl; then say ">>> curl is required. Please install curl and re-run."; exit 1; fi
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Add brew to PATH for this session (common locations)
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
  ensure_path_has_common_bins
}

# --- uv install (optional) --------------------------------------------------
install_uv() {
  if has_cmd uv; then
    say ">>> uv present: $(uv --version 2>/dev/null || echo ok)"
    return
  fi
  if ! ask_yes_no "uv not found. Install uv now?"; then return; fi
  if ! has_cmd curl; then say ">>> curl is required to install uv. Please install curl and re-run."; exit 1; fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Add uv to PATH for this session
  [ -d "$HOME/.local/bin" ] && export PATH="$HOME/.local/bin:$PATH"
  [ -d "$HOME/.cargo/bin" ] && export PATH="$HOME/.cargo/bin:$PATH"
}

# --- Docker: install if missing (never reinstall) ---------------------------
install_docker_if_missing() {
  if has_cmd docker; then
    say ">>> Docker CLI detected at: $(docker_cli_path)"
    say ">>> Version: $(docker --version 2>/dev/null || echo 'unknown')"
    return
  fi
  say ">>> Docker CLI not found."
  if ! ask_yes_no "Install Docker now?"; then return; fi

  case "$PLATFORM" in
    macOS)
      # Ensure Homebrew is available for Docker Desktop installation
      if ! has_cmd brew; then
        install_homebrew_if_missing || {
          say ">>> Cannot install Docker Desktop without Homebrew."
          say ">>> Please download manually from: https://www.docker.com/products/docker-desktop/"
          exit 1
        }
      fi
      if has_cmd brew; then
        say ">>> Installing Docker Desktop via Homebrew..."
        brew install --cask docker
        say ">>> Starting Docker Desktop..."
        open -gj -a Docker || true
      fi
      ;;
    Linux|WSL)
      if ! has_cmd curl; then say ">>> Need curl to install Docker. Install curl and re-run."; exit 1; fi
      curl -fsSL https://get.docker.com | $SUDO sh
      # Do NOT assume docker group exists everywhere; creation is distro-dependent
      if getent group docker >/dev/null 2>&1; then
        $SUDO usermod -aG docker "$USER" || true
      fi
      ;;
    *)
      say ">>> Unsupported platform for automated Docker install."
      ;;
  esac
}

# --- Docker daemon start/wait (sudo only if starting service) ---------------
start_docker_daemon_if_needed() {
  if docker_daemon_ready; then
    say ">>> Docker daemon is ready."
    return 0
  fi

  say ">>> Docker CLI found but daemon not reachable."
  case "$PLATFORM" in
    macOS)
      say ">>> Attempting to start Docker Desktop..."
      open -gj -a Docker || true
      ;;
    Linux|WSL)
      say ">>> Attempting to start docker service (may prompt for sudo)..."
      $SUDO systemctl start docker >/dev/null 2>&1 || $SUDO service docker start >/dev/null 2>&1 || true
      ;;
  esac

  for i in {1..60}; do
    docker_daemon_ready && { say ">>> Docker daemon is ready."; return 0; }
    sleep 2
  done

  say ">>> Still not reachable. If Linux: check 'systemctl status docker' and group membership."
  say ">>> If macOS: open Docker.app and wait for 'Docker Desktop is running'."
  return 1
}

# --- Docker group activation (safe: only if group exists) -------------------
activate_docker_group_now() {
  [ "$PLATFORM" = "Linux" ] || [ "$PLATFORM" = "WSL" ] || return 0
  has_cmd docker || return 0

  # only act if the docker group actually exists
  if ! getent group docker >/dev/null 2>&1; then
    return 0
  fi

  # If user already in group, nothing to do
  if id -nG "$USER" 2>/dev/null | grep -qw docker; then return 0; fi

  # Re-enter with sg if available
  if has_cmd sg; then
    if [ -z "${REENTERED_WITH_DOCKER_GROUP:-}" ]; then
      say ">>> Re-entering shell with 'docker' group active for this run..."
      export REENTERED_WITH_DOCKER_GROUP=1
      exec sg docker -c "REENTERED_WITH_DOCKER_GROUP=1 bash \"$0\""
    fi
  else
    say ">>> You were likely added to 'docker' group. Open a new shell or run: newgrp docker"
  fi
}

# --- Compose detection/offer (no reinstall) ---------------------------------
check_or_offer_compose() {
  if compose_v2_ready; then
    say ">>> Docker Compose v2 available (docker compose)."
    return 0
  fi
  if compose_v1_ready; then
    say ">>> docker-compose (v1) available: $(docker-compose --version 2>/dev/null || echo ok)"
    return 0
  fi

  say ">>> Docker Compose not found."
  if ! ask_yes_no "Install Docker Compose plugin (v2)?"; then
    say ">>> Skipping Compose install."
    return 1
  fi

  case "$PLATFORM" in
    macOS)
      say ">>> On macOS, Docker Desktop bundles Compose v2. Starting Desktop…"
      open -gj -a Docker || true
      ;;
    Linux|WSL)
      if   has_cmd apt-get; then $SUDO apt-get update -y && $SUDO apt-get install -y docker-compose-plugin || true
      elif has_cmd dnf;     then $SUDO dnf install -y docker-compose-plugin || true
      elif has_cmd yum;     then $SUDO yum install -y docker-compose-plugin || true
      elif has_cmd zypper;  then $SUDO zypper install -y docker-compose docker-compose-plugin || true
      elif has_cmd pacman;  then $SUDO pacman -Sy --noconfirm docker-compose || true
      else
        say ">>> Please install Compose via your distro's instructions."
      fi
      ;;
  esac

  if compose_v2_ready || compose_v1_ready; then
    say ">>> Compose is now available."
  else
    say ">>> Could not verify Compose installation automatically."
  fi
}

# --- Podman: install if missing (never reinstall) ---------------------------
install_podman_if_missing() {
  if has_cmd podman; then
    say ">>> Podman CLI detected at: $(podman_cli_path)"
    say ">>> Version: $(podman --version 2>/dev/null || echo 'unknown')"
    return
  fi
  say ">>> Podman CLI not found."
  if ! ask_yes_no "Install Podman now?"; then return; fi

  case "$PLATFORM" in
    macOS)
      # Ensure Homebrew is available for Podman installation
      if ! has_cmd brew; then
        install_homebrew_if_missing || {
          say ">>> Cannot install Podman without Homebrew."
          say ">>> Please install manually from: https://podman.io/getting-started/installation"
          exit 1
        }
      fi
      if has_cmd brew; then
        # Install krunkit if not present
        if ! brew list krunkit >/dev/null 2>&1; then
          say ">>> Installing krunkit (Podman dependency)..."
          brew tap slp/krunkit
          brew install krunkit
        else
          say ">>> krunkit already installed."
        fi
        say ">>> Installing Podman..."
        brew install podman
        say ">>> Installing Podman Desktop..."
        brew install --cask podman-desktop
      fi
      ;;
    Linux|WSL)
      if   has_cmd apt-get; then $SUDO apt-get update -y && $SUDO apt-get install -y podman
      elif has_cmd dnf;     then $SUDO dnf install -y podman
      elif has_cmd yum;     then $SUDO yum install -y podman
      elif has_cmd zypper;  then $SUDO zypper install -y podman
      elif has_cmd pacman;  then $SUDO pacman -Sy --noconfirm podman
      else
        say ">>> Please install 'podman' via your distro."
      fi
      ;;
  esac
}

ensure_podman_ready() {
  if [ "$PLATFORM" = "macOS" ]; then
    local machine_name="podman-machine-default"
    local min_memory_mb=8192  # 8 GB minimum

    # Check if any machine exists
    if ! podman machine list 2>/dev/null | tail -n +2 | grep -q .; then
      say ">>> Podman machine does not exist. Initializing with 8GB memory (rootful mode)…"
      # Clean up orphaned system connections if they exist
      if podman system connection list 2>/dev/null | tail -n +2 | grep -q .; then
        say ">>> Removing orphaned system connections..."
        # Remove all connections to ensure clean slate
        podman system connection list 2>/dev/null | tail -n +2 | awk '{print $1}' | while read -r conn; do
          podman system connection rm "$conn" 2>/dev/null || true
        done
      fi
      podman machine init --memory "$min_memory_mb" --rootful || {
        say ">>> Failed to initialize Podman machine."
        return 1
      }
    else
      # Machine exists - check if it has enough memory
      say ">>> Checking Podman machine configuration…"
      local current_memory
      current_memory=$(podman machine inspect "$machine_name" --format "{{.Resources.Memory}}" 2>/dev/null || echo "0")

      if [ "$current_memory" -gt 0 ] && [ "$current_memory" -lt "$min_memory_mb" ]; then
        say ">>> Podman machine has ${current_memory}MB memory, but ${min_memory_mb}MB is recommended."
        if ask_yes_no "Recreate Podman machine with ${min_memory_mb}MB memory?"; then
          say ">>> Stopping and removing existing Podman machine…"
          podman machine stop 2>/dev/null || true
          podman machine rm -f "$machine_name" || {
            say ">>> Failed to remove existing machine."
            return 1
          }
          say ">>> Initializing new Podman machine with ${min_memory_mb}MB memory (rootful mode)…"
          podman machine init --memory "$min_memory_mb" --rootful || {
            say ">>> Failed to initialize Podman machine."
            return 1
          }
        else
          say ">>> Continuing with existing machine (may have insufficient resources)."
        fi
      fi
    fi

    # Now check if it's running
    if ! podman machine list 2>/dev/null | grep -q running; then
      say ">>> Starting Podman machine (macOS)…"
      podman machine start || {
        say ">>> Failed to start Podman machine."
        return 1
      }
      for i in {1..30}; do podman_ready && break || sleep 2; done
    fi
  fi
  if podman_ready; then
    say ">>> Podman is ready."
    return 0
  else
    say ">>> Podman CLI present but not ready (try 'podman machine start' on macOS)."
    return 1
  fi
}

# --- Runtime auto-detect (prefer no prompt) ---------------------------------
hr
say "Platform: $PLATFORM"
hr

# uv (optional)
if has_cmd uv; then say ">>> uv present: $(uv --version 2>/dev/null || echo ok)"; else install_uv; fi

RUNTIME=""
if docker_is_podman; then
  say ">>> Detected podman-docker shim: using Podman runtime."
  RUNTIME="Podman"
elif has_cmd docker; then
  say ">>> Docker CLI detected."
  RUNTIME="Docker"
elif has_cmd podman; then
  say ">>> Podman CLI detected."
  RUNTIME="Podman"
fi

if [ -z "$RUNTIME" ]; then
  say "Choose container runtime:"
  PS3="Select [1-2]: "
  select rt in "Docker" "Podman"; do
    case "$REPLY" in 1|2) RUNTIME="$rt"; break ;; *) say "Invalid choice";; esac
  done
fi

say "Selected runtime: $RUNTIME"
hr

# --- Execute runtime path ----------------------------------------------------
if [ "$RUNTIME" = "Docker" ]; then
  install_docker_if_missing          # no reinstall if present
  activate_docker_group_now          # safe: only if group exists and user not in it
  start_docker_daemon_if_needed      # sudo only to start service on Linux/WSL
  check_or_offer_compose             # offer to install Compose only if missing
else
  install_podman_if_missing          # no reinstall if present
  ensure_podman_ready
  # Optional: podman-compose for compose-like UX
  if ! command -v podman-compose >/dev/null 2>&1 && ! podman compose version >/dev/null 2>&1; then
    if ask_yes_no "Install podman-compose (optional)?"; then
      if [ "$PLATFORM" = "macOS" ]; then
        # Ensure Homebrew is available for podman-compose on macOS
        if ! has_cmd brew; then
          install_homebrew_if_missing || say ">>> Install podman-compose manually or via pip3"
        fi
        if has_cmd brew; then
          brew install podman-compose
        fi
      elif has_cmd apt-get; then $SUDO apt-get update -y && $SUDO apt-get install -y podman-compose || pip3 install --user podman-compose || true
      elif has_cmd dnf;     then $SUDO dnf install -y podman-compose || true
      elif has_cmd yum;     then $SUDO yum install -y podman-compose || true
      elif has_cmd zypper;  then $SUDO zypper install -y podman-compose || true
      elif has_cmd pacman;  then $SUDO pacman -Sy --noconfirm podman-compose || true
      else say ">>> Please install podman-compose via your distro."; fi
    fi
  fi
fi

hr
say "Environment ready — launching: uvx openrag"
hr

if ! has_cmd uv; then
  say ">>> 'uv' not on PATH. Add the installer’s bin dir to PATH, then run: uvx openrag"
  exit 1
fi

exec uvx openrag

