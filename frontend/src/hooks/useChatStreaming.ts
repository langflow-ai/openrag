import { useRef, useState } from "react";
import type { FunctionCall, Message, SelectedFilters } from "@/app/chat/types";

interface UseChatStreamingOptions {
	endpoint?: string;
	onComplete?: (message: Message, responseId: string | null) => void;
	onError?: (error: Error) => void;
}

interface SendMessageOptions {
	prompt: string;
	previousResponseId?: string;
	filters?: SelectedFilters;
	limit?: number;
	scoreThreshold?: number;
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

	const sendMessage = async ({
		prompt,
		previousResponseId,
		filters,
		limit = 10,
		scoreThreshold = 0,
	}: SendMessageOptions) => {
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
				filters?: SelectedFilters;
				limit?: number;
				scoreThreshold?: number;
			} = {
				prompt,
				stream: true,
				limit,
				scoreThreshold,
			};

			if (previousResponseId) {
				requestBody.previous_response_id = previousResponseId;
			}

			if (filters) {
				requestBody.filters = filters;
			}

			const response = await fetch(endpoint, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
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

								// Handle OpenAI Chat Completions streaming format
								if (chunk.object === "response.chunk" && chunk.delta) {
									// Handle function calls in delta
									if (chunk.delta.function_call) {
										if (chunk.delta.function_call.name) {
											const functionCall: FunctionCall = {
												name: chunk.delta.function_call.name,
												arguments: undefined,
												status: "pending",
												argumentsString:
													chunk.delta.function_call.arguments || "",
											};
											currentFunctionCalls.push(functionCall);
										} else if (chunk.delta.function_call.arguments) {
											const lastFunctionCall =
												currentFunctionCalls[currentFunctionCalls.length - 1];
											if (lastFunctionCall) {
												if (!lastFunctionCall.argumentsString) {
													lastFunctionCall.argumentsString = "";
												}
												lastFunctionCall.argumentsString +=
													chunk.delta.function_call.arguments;

												if (lastFunctionCall.argumentsString.includes("}")) {
													try {
														const parsed = JSON.parse(
															lastFunctionCall.argumentsString
														);
														lastFunctionCall.arguments = parsed;
														lastFunctionCall.status = "completed";
													} catch (e) {
														// Arguments not yet complete
													}
												}
											}
										}
									}
									// Handle tool calls in delta
									else if (
										chunk.delta.tool_calls &&
										Array.isArray(chunk.delta.tool_calls)
									) {
										for (const toolCall of chunk.delta.tool_calls) {
											if (toolCall.function) {
												if (toolCall.function.name) {
													const functionCall: FunctionCall = {
														name: toolCall.function.name,
														arguments: undefined,
														status: "pending",
														argumentsString: toolCall.function.arguments || "",
													};
													currentFunctionCalls.push(functionCall);
												} else if (toolCall.function.arguments) {
													const lastFunctionCall =
														currentFunctionCalls[
															currentFunctionCalls.length - 1
														];
													if (lastFunctionCall) {
														if (!lastFunctionCall.argumentsString) {
															lastFunctionCall.argumentsString = "";
														}
														lastFunctionCall.argumentsString +=
															toolCall.function.arguments;

														if (
															lastFunctionCall.argumentsString.includes("}")
														) {
															try {
																const parsed = JSON.parse(
																	lastFunctionCall.argumentsString
																);
																lastFunctionCall.arguments = parsed;
																lastFunctionCall.status = "completed";
															} catch (e) {
																// Arguments not yet complete
															}
														}
													}
												}
											}
										}
									}
									// Handle content/text in delta
									else if (chunk.delta.content) {
										currentContent += chunk.delta.content;
									}

									// Handle finish reason
									if (chunk.delta.finish_reason) {
										currentFunctionCalls.forEach((fc) => {
											if (fc.status === "pending" && fc.argumentsString) {
												try {
													fc.arguments = JSON.parse(fc.argumentsString);
													fc.status = "completed";
												} catch (e) {
													fc.arguments = { raw: fc.argumentsString };
													fc.status = "error";
												}
											}
										});
									}
								}
								// Handle Realtime API format - function call added
								else if (
									chunk.type === "response.output_item.added" &&
									chunk.item?.type === "function_call"
								) {
									let existing = currentFunctionCalls.find(
										(fc) => fc.id === chunk.item.id
									);
									if (!existing) {
										existing = [...currentFunctionCalls]
											.reverse()
											.find(
												(fc) =>
													fc.status === "pending" &&
													!fc.id &&
													fc.name === (chunk.item.tool_name || chunk.item.name)
											);
									}

									if (existing) {
										existing.id = chunk.item.id;
										existing.type = chunk.item.type;
										existing.name =
											chunk.item.tool_name || chunk.item.name || existing.name;
										existing.arguments =
											chunk.item.inputs || existing.arguments;
									} else {
										const functionCall: FunctionCall = {
											name:
												chunk.item.tool_name || chunk.item.name || "unknown",
											arguments: chunk.item.inputs || undefined,
											status: "pending",
											argumentsString: "",
											id: chunk.item.id,
											type: chunk.item.type,
										};
										currentFunctionCalls.push(functionCall);
									}
								}
								// Handle Realtime API format - tool call added
								else if (
									chunk.type === "response.output_item.added" &&
									chunk.item?.type?.includes("_call") &&
									chunk.item?.type !== "function_call"
								) {
									let existing = currentFunctionCalls.find(
										(fc) => fc.id === chunk.item.id
									);
									if (!existing) {
										existing = [...currentFunctionCalls]
											.reverse()
											.find(
												(fc) =>
													fc.status === "pending" &&
													!fc.id &&
													fc.name ===
														(chunk.item.tool_name ||
															chunk.item.name ||
															chunk.item.type)
											);
									}

									if (existing) {
										existing.id = chunk.item.id;
										existing.type = chunk.item.type;
										existing.name =
											chunk.item.tool_name ||
											chunk.item.name ||
											chunk.item.type ||
											existing.name;
										existing.arguments =
											chunk.item.inputs || existing.arguments;
									} else {
										const functionCall = {
											name:
												chunk.item.tool_name ||
												chunk.item.name ||
												chunk.item.type ||
												"unknown",
											arguments: chunk.item.inputs || {},
											status: "pending" as const,
											id: chunk.item.id,
											type: chunk.item.type,
										};
										currentFunctionCalls.push(functionCall);
									}
								}
								// Handle function call done
								else if (
									chunk.type === "response.output_item.done" &&
									chunk.item?.type === "function_call"
								) {
									const functionCall = currentFunctionCalls.find(
										(fc) =>
											fc.id === chunk.item.id ||
											fc.name === chunk.item.tool_name ||
											fc.name === chunk.item.name
									);

									if (functionCall) {
										functionCall.status =
											chunk.item.status === "completed" ? "completed" : "error";
										functionCall.id = chunk.item.id;
										functionCall.type = chunk.item.type;
										functionCall.name =
											chunk.item.tool_name ||
											chunk.item.name ||
											functionCall.name;
										functionCall.arguments =
											chunk.item.inputs || functionCall.arguments;

										if (chunk.item.results) {
											functionCall.result = chunk.item.results;
										}
									}
								}
								// Handle tool call done with results
								else if (
									chunk.type === "response.output_item.done" &&
									chunk.item?.type?.includes("_call") &&
									chunk.item?.type !== "function_call"
								) {
									const functionCall = currentFunctionCalls.find(
										(fc) =>
											fc.id === chunk.item.id ||
											fc.name === chunk.item.tool_name ||
											fc.name === chunk.item.name ||
											fc.name === chunk.item.type ||
											fc.name.includes(chunk.item.type.replace("_call", "")) ||
											chunk.item.type.includes(fc.name)
									);

									if (functionCall) {
										functionCall.arguments =
											chunk.item.inputs || functionCall.arguments;
										functionCall.status =
											chunk.item.status === "completed" ? "completed" : "error";
										functionCall.id = chunk.item.id;
										functionCall.type = chunk.item.type;

										if (chunk.item.results) {
											functionCall.result = chunk.item.results;
										}
									} else {
										const newFunctionCall = {
											name:
												chunk.item.tool_name ||
												chunk.item.name ||
												chunk.item.type ||
												"unknown",
											arguments: chunk.item.inputs || {},
											status: "completed" as const,
											id: chunk.item.id,
											type: chunk.item.type,
											result: chunk.item.results,
										};
										currentFunctionCalls.push(newFunctionCall);
									}
								}
								// Handle text output streaming (Realtime API)
								else if (chunk.type === "response.output_text.delta") {
									currentContent += chunk.delta || "";
								}
								// Handle OpenRAG backend format
								else if (chunk.output_text) {
									currentContent += chunk.output_text;
								} else if (chunk.delta) {
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
