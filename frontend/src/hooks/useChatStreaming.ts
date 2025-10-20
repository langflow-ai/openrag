import { useRef, useState } from "react";
import type { FunctionCall, Message } from "@/app/chat/types";

interface UseChatStreamingOptions {
	endpoint?: string;
	onComplete?: (message: Message, responseId: string | null) => void;
	onError?: (error: Error) => void;
}

export function useChatStreaming({
	endpoint = "/api/chat",
	onComplete,
	onError,
}: UseChatStreamingOptions = {}) {
	const [streamingMessage, setStreamingMessage] = useState<Message | null>(
		null,
	);
	const [isLoading, setIsLoading] = useState(false);
	const streamAbortRef = useRef<AbortController | null>(null);
	const streamIdRef = useRef(0);

	const sendMessage = async (prompt: string, previousResponseId?: string) => {
		try {
			setIsLoading(true);

			// Abort any existing stream before starting a new one
			if (streamAbortRef.current) {
				streamAbortRef.current.abort();
			}

			const controller = new AbortController();
			streamAbortRef.current = controller;
			const thisStreamId = ++streamIdRef.current;

			const requestBody: {
				prompt: string;
				stream: boolean;
				previous_response_id?: string;
			} = {
				prompt,
				stream: true,
			};

			if (previousResponseId) {
				requestBody.previous_response_id = previousResponseId;
			}

			const response = await fetch(endpoint, {
				method: "POST",
				headers: {
					"Content-Type": "text/event-stream",
				},
				body: JSON.stringify(requestBody),
				signal: controller.signal,
			});

			if (!response.ok) {
				throw new Error(`HTTP error! status: ${response.status}`);
			}

			const reader = response.body?.getReader();
			if (!reader) {
				throw new Error("No reader available");
			}

			const decoder = new TextDecoder();
			let buffer = "";
			let currentContent = "";
			const currentFunctionCalls: FunctionCall[] = [];
			let newResponseId: string | null = null;

			// Initialize streaming message
			if (!controller.signal.aborted && thisStreamId === streamIdRef.current) {
				setStreamingMessage({
					role: "assistant",
					content: "",
					timestamp: new Date(),
					isStreaming: true,
				});
			}

			try {
				while (true) {
					const { done, value } = await reader.read();
					if (controller.signal.aborted || thisStreamId !== streamIdRef.current)
						break;
					if (done) break;

					buffer += decoder.decode(value, { stream: true });

					// Process complete lines (JSON objects)
					const lines = buffer.split("\n");
					buffer = lines.pop() || ""; // Keep incomplete line in buffer

					for (const line of lines) {
						if (line.trim()) {
							try {
								const chunk = JSON.parse(line);

								// Extract response ID if present
								if (chunk.id) {
									newResponseId = chunk.id;
								} else if (chunk.response_id) {
									newResponseId = chunk.response_id;
								}

								// Handle OpenRAG backend format (from agent.py async_response_stream)
								// The chunk is serialized via chunk.model_dump() and contains output_text or delta
								if (chunk.output_text) {
									// Direct output text from chunk
									currentContent += chunk.output_text;
								} else if (chunk.delta) {
									// Handle delta - could be string, dict, or have content/text properties
									if (typeof chunk.delta === "string") {
										currentContent += chunk.delta;
									} else if (typeof chunk.delta === "object") {
										if (chunk.delta.content) {
											currentContent += chunk.delta.content;
										} else if (chunk.delta.text) {
											currentContent += chunk.delta.text;
										}
									}
								}

								// Update streaming message in real-time
								if (
									!controller.signal.aborted &&
									thisStreamId === streamIdRef.current
								) {
									setStreamingMessage({
										role: "assistant",
										content: currentContent,
										functionCalls:
											currentFunctionCalls.length > 0
												? [...currentFunctionCalls]
												: undefined,
										timestamp: new Date(),
										isStreaming: true,
									});
								}
							} catch (parseError) {
								console.warn("Failed to parse chunk:", line, parseError);
							}
						}
					}
				}
			} finally {
				reader.releaseLock();
			}

			// Finalize the message
			const finalMessage: Message = {
				role: "assistant",
				content: currentContent,
				functionCalls:
					currentFunctionCalls.length > 0 ? currentFunctionCalls : undefined,
				timestamp: new Date(),
				isStreaming: false,
			};

			if (!controller.signal.aborted && thisStreamId === streamIdRef.current) {
				// Clear streaming message and call onComplete with final message
				setStreamingMessage(null);
				onComplete?.(finalMessage, newResponseId);
				return finalMessage;
			}

			return null;
		} catch (error) {
			// If stream was aborted, don't handle as error
			if (streamAbortRef.current?.signal.aborted) {
				return null;
			}

			console.error("SSE Stream error:", error);
			setStreamingMessage(null);
			onError?.(error as Error);

			const errorMessage: Message = {
				role: "assistant",
				content:
					"Sorry, I couldn't connect to the chat service. Please try again.",
				timestamp: new Date(),
				isStreaming: false,
			};

			return errorMessage;
		} finally {
			setIsLoading(false);
		}
	};

	const abortStream = () => {
		if (streamAbortRef.current) {
			streamAbortRef.current.abort();
		}
		setStreamingMessage(null);
		setIsLoading(false);
	};

	return {
		streamingMessage,
		isLoading,
		sendMessage,
		abortStream,
	};
}
