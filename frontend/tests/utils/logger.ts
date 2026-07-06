import path from "path";
import winston from "winston";

const logDir = "logs";

// Define log format
const logFormat = winston.format.combine(
  winston.format.timestamp({ format: "YYYY-MM-DD HH:mm:ss" }),
  winston.format.errors({ stack: true }),
  winston.format.splat(),
  winston.format.json(),
);

// Define console format for better readability
const consoleFormat = winston.format.combine(
  winston.format.colorize(),
  winston.format.timestamp({ format: "YYYY-MM-DD HH:mm:ss" }),
  winston.format.printf(({ timestamp, level, message, ...meta }) => {
    let msg = `${timestamp} [${level}]: ${message}`;
    if (Object.keys(meta).length > 0) {
      msg += ` ${JSON.stringify(meta)}`;
    }
    return msg;
  }),
);

type LoggerWithStream = winston.Logger & {
  morganStream: {
    write: (message: string) => void;
  };
};

// Create logger instance
const logger = winston.createLogger({
  level: process.env.LOG_LEVEL || "info",
  format: logFormat,
  transports: [
    new winston.transports.Console({ format: consoleFormat }),
    new winston.transports.File({
      filename: path.join(logDir, "error.log"),
      level: "error",
      maxsize: 5242880,
      maxFiles: 5,
    }),
    new winston.transports.File({
      filename: path.join(logDir, "combined.log"),
      maxsize: 5242880,
      maxFiles: 5,
    }),
  ],
  exitOnError: false,
}) as LoggerWithStream;

// Create a stream object for Morgan or other middleware
logger.morganStream = {
  write: (message: string) => {
    logger.info(message.trim());
  },
};

export default logger;

// Helper functions for common logging patterns
export const logTestStart = (testName: string) => {
  logger.info(`========== Starting Test: ${testName} ==========`);
};

export const logTestEnd = (testName: string, status: "PASSED" | "FAILED") => {
  logger.info(`========== Test ${status}: ${testName} ==========`);
};

export const logStep = (step: string) => {
  logger.info(`Step: ${step}`);
};

export const logError = (error: Error | string, context?: any) => {
  if (error instanceof Error) {
    logger.error(`Error: ${error.message}`, { stack: error.stack, context });
  } else {
    logger.error(`Error: ${error}`, { context });
  }
};

export const logWarning = (message: string, context?: any) => {
  logger.warn(message, context);
};

export const logDebug = (message: string, data?: any) => {
  logger.debug(message, data);
};
