/**
 * Generates a personalised, time- and day-aware greeting for the chat
 * initial message. A random variant is chosen per call so different
 * sessions feel fresh.
 */

type TimeSlot = "morning" | "afternoon" | "evening" | "latenight";

function getTimeSlot(hour: number): TimeSlot {
  if (hour >= 6 && hour < 12) return "morning";
  if (hour >= 12 && hour < 18) return "afternoon";
  if (hour >= 18 && hour < 24) return "evening";
  return "latenight";
}

const GREETING_MESSAGES: Record<TimeSlot, string[]> = {
  morning: [
    "Good morning{name}! How can I assist you today?",
    "Morning{name}! How can I help?",
    "Good morning{name}! What can I help you with?",
    "Good morning{name}! How may I help you today?",
    "Morning{name}! What are we working on today?",
  ],
  afternoon: [
    "Good afternoon{name}! How can I assist?",
    "Afternoon{name}! How can I help you today?",
    "Good afternoon{name}! What can I do for you?",
    "Good afternoon{name}! How may I assist you?",
    "Afternoon{name}! What are we working on?",
  ],
  evening: [
    "Good evening{name}! How can I assist?",
    "Evening{name}! How can I help you?",
    "Good evening{name}! What can I do for you?",
    "Good evening{name}! How may I assist you?",
    "Evening{name}! What are we working on tonight?",
  ],
  latenight: [
    "Hey{name}! How can I assist you tonight?",
    "Still up{name}? How can I help?",
    "Late night{name}! What can I do for you?",
    "Hey{name}! How may I help you?",
    "Working late{name}? How can I assist?",
  ],
};

const DAY_OF_WEEK_MESSAGES: Record<number, string[]> = {
  // 0 = Sunday, 1 = Monday … 6 = Saturday
  0: [
    "Happy Sunday{name}! How can I assist?",
    "Enjoying your Sunday{name}? How can I help?",
  ],
  1: [
    "Happy Monday{name}! How can I assist?",
    "New week{name}! How can I help you today?",
  ],
  2: ["Happy Tuesday{name}! How can I assist?"],
  3: ["Happy Wednesday{name}! How can I assist?"],
  4: [
    "Happy Thursday{name}! How can I assist?",
    "Almost Friday{name}! How can I help you today?",
  ],
  5: [
    "Happy Friday{name}! How can I assist?",
    "TGIF{name}! How can I help you today?",
  ],
  6: [
    "Happy Saturday{name}! How can I assist?",
    "Enjoying the weekend{name}? How can I help?",
  ],
};

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

/**
 * Returns a short, cheerful, personalized greeting.
 *
 * @param displayName  The user's preferred name (display_name) or full OAuth name.
 *                     Pass undefined/null/empty for an anonymous greeting.
 */
export function getGreetingMessage(displayName?: string | null): string {
  const firstName = displayName?.trim().split(/\s+/)[0] ?? "";
  const nameInsertion = firstName ? `, ${firstName}` : "";

  const now = new Date();
  const day = now.getDay();
  const hour = now.getHours();

  const dayVariants = DAY_OF_WEEK_MESSAGES[day];
  if (dayVariants && Math.random() < 0.35) {
    //subject to change, set at 35% for now
    return pick(dayVariants).replace("{name}", nameInsertion);
  }

  const slot = getTimeSlot(hour);
  return pick(GREETING_MESSAGES[slot]).replace("{name}", nameInsertion);
}
