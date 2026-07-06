import { Settings } from "../pages/Settings";
import logger from "./logger";

export async function runTransitionSequence(
  settings: Settings,
  section: string,
  sequence: string[],
): Promise<string[]> {
  const failures: string[] = [];

  // 🔹 Initialize with first model
  await settings.selectModel(section, sequence[0]);

  for (let i = 0; i < sequence.length - 1; i++) {
    const from = sequence[i];
    const to = sequence[i + 1];

    logger.info(`🔄 Transition: ${from} → ${to}`);

    try {
      await settings.selectModel(section, to);
      logger.info(`✅ Success: ${from} → ${to}`);
    } catch (_err) {
      logger.error(`❌ Failed: ${from} → ${to}`);
      failures.push(`${from} → ${to}`);
    }
  }

  return failures;
}
