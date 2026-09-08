interface NavigationClick {
  button: number;
  href: string;
  currentHref: string;
  target?: string;
  download?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
}

export function getInterceptedNavigationHref({
  button,
  href,
  currentHref,
  target,
  download,
  metaKey,
  ctrlKey,
  shiftKey,
  altKey,
}: NavigationClick): string | null {
  if (
    button !== 0 ||
    metaKey ||
    ctrlKey ||
    shiftKey ||
    altKey ||
    (target && target.toLowerCase() !== "_self") ||
    download
  ) {
    return null;
  }

  const currentUrl = new URL(currentHref);
  const destinationUrl = new URL(href, currentUrl);
  if (
    destinationUrl.origin !== currentUrl.origin ||
    (destinationUrl.pathname === currentUrl.pathname &&
      destinationUrl.search === currentUrl.search)
  ) {
    return null;
  }

  return `${destinationUrl.pathname}${destinationUrl.search}${destinationUrl.hash}`;
}
