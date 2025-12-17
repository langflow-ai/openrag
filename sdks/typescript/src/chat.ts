/**
 * OpenRAG SDK chat client with streaming support.
 */

import type { OpenRAGClient } from "./client";
import type {
  ChatCreateOptions,
  ChatResponse,
  ContentEvent,
  Conversation,
  ConversationDetail,
  ConversationListResponse,
  DoneEvent,
  Message,
  Source,
  SourcesEvent,
  StreamEvent,
} from "./types";

/**
 * Streaming chat response with helpers.
 *
 * Usage:
 * ```typescript
 * using stream = await client.chat.stream({ message: "Hello" });
 * for await (const event of stream) {
 *   if (event.type === "content") console.log(event.delta);
 * }
 * console.log(stream.chatId);
 * console.log(stream.text);
 * ```
 */
export class ChatStream implements AsyncIterable<StreamEvent>, Disposable {
  private _text = "";
  private _chatId: string | null = null;
  private _sources: Source[] = [];
  private _consumed = false;
  private _reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private _response: Response | null = null;

  constructor(
    private client: OpenRAGClient,
    private options: ChatCreateOptions
  ) {}

  /** The accumulated text from content events. */
  get text(): string {
    return this._text;
  }

  /** The chat ID for continuing the conversation. */
  get chatId(): string | null {
    return this._chatId;
  }

  /** The sources retrieved during the conversation. */
  get sources(): Source[] {
    return this._sources;
  }

  /** @internal Initialize the stream. */
  async _init(): Promise<void> {
    const body: Record<string, unknown> = {
      message: this.options.message,
      stream: true,
      limit: this.options.limit ?? 10,
      score_threshold: this.options.scoreThreshold ?? 0,
    };

    if (this.options.chatId) {
      body["chat_id"] = this.options.chatId;
    }

    if (this.options.filters) {
      body["filters"] = this.options.filters;
    }

    this._response = await this.client._request("POST", "/api/v1/chat", {
      body: JSON.stringify(body),
      stream: true,
    });

    if (!this._response.body) {
      throw new Error("Response body is null");
    }

    this._reader = this._response.body.getReader();
  }

  async *[Symbol.asyncIterator](): AsyncIterator<StreamEvent> {
    if (this._consumed) {
      throw new Error("Stream has already been consumed");
    }
    this._consumed = true;

    if (!this._reader) {
      throw new Error("Stream not initialized");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await this._reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith("data:")) continue;

        const dataStr = trimmed.slice(5).trim();
        if (!dataStr) continue;

        try {
          const data = JSON.parse(dataStr);
          const eventType = data.type;

          if (eventType === "content") {
            const delta = data.delta || "";
            this._text += delta;
            yield { type: "content", delta } as ContentEvent;
          } else if (eventType === "sources") {
            this._sources = data.sources || [];
            yield { type: "sources", sources: this._sources } as SourcesEvent;
          } else if (eventType === "done") {
            this._chatId = data.chat_id || null;
            yield { type: "done", chatId: this._chatId } as DoneEvent;
          }
        } catch {
          // Ignore parse errors
        }
      }
    }
  }

  /**
   * Iterate over just the text deltas.
   */
  get textStream(): AsyncIterable<string> {
    const self = this;
    return {
      async *[Symbol.asyncIterator]() {
        for await (const event of self) {
          if (event.type === "content") {
            yield event.delta;
          }
        }
      },
    };
  }

  /**
   * Consume the stream and return the complete text.
   */
  async finalText(): Promise<string> {
    for await (const _ of this) {
      // Consume all events
    }
    return this._text;
  }

  /** Clean up resources. */
  [Symbol.dispose](): void {
    this._reader?.cancel().catch(() => {});
  }

  /** Close the stream. */
  close(): void {
    this[Symbol.dispose]();
  }
}

export class ChatClient {
  constructor(private client: OpenRAGClient) {}

  /**
   * Send a chat message (non-streaming).
   */
  async create(options: ChatCreateOptions & { stream?: false }): Promise<ChatResponse>;
  /**
   * Send a chat message (streaming).
   */
  async create(
    options: ChatCreateOptions & { stream: true }
  ): Promise<AsyncIterable<StreamEvent>>;
  /**
   * Send a chat message.
   *
   * @param options - Chat options including message, stream flag, etc.
   * @returns ChatResponse if stream=false, AsyncIterable<StreamEvent> if stream=true.
   */
  async create(
    options: ChatCreateOptions
  ): Promise<ChatResponse | AsyncIterable<StreamEvent>> {
    if (options.stream) {
      return this._createStreamingIterator(options);
    }
    return this._createNonStreaming(options);
  }

  private async _createNonStreaming(options: ChatCreateOptions): Promise<ChatResponse> {
    const body: Record<string, unknown> = {
      message: options.message,
      stream: false,
      limit: options.limit ?? 10,
      score_threshold: options.scoreThreshold ?? 0,
    };

    if (options.chatId) {
      body["chat_id"] = options.chatId;
    }

    if (options.filters) {
      body["filters"] = options.filters;
    }

    const response = await this.client._request("POST", "/api/v1/chat", {
      body: JSON.stringify(body),
    });

    const data = await response.json();
    return {
      response: data.response || "",
      chatId: data.chat_id || null,
      sources: data.sources || [],
    };
  }

  private async _createStreamingIterator(
    options: ChatCreateOptions
  ): Promise<AsyncIterable<StreamEvent>> {
    const stream = new ChatStream(this.client, options);
    await stream._init();
    return stream;
  }

  /**
   * Create a streaming chat context manager.
   *
   * @param options - Chat options.
   * @returns ChatStream with helpers.
   */
  async stream(options: Omit<ChatCreateOptions, "stream">): Promise<ChatStream> {
    const stream = new ChatStream(this.client, { ...options, stream: true });
    await stream._init();
    return stream;
  }

  /**
   * List all conversations.
   */
  async list(): Promise<ConversationListResponse> {
    const response = await this.client._request("GET", "/api/v1/chat");
    const data = await response.json();

    const conversations: Conversation[] = (data.conversations || []).map(
      (c: Record<string, unknown>) => ({
        chatId: c["chat_id"],
        title: c["title"] || "",
        createdAt: c["created_at"] || null,
        lastActivity: c["last_activity"] || null,
        messageCount: c["message_count"] || 0,
      })
    );

    return { conversations };
  }

  /**
   * Get a specific conversation with full message history.
   *
   * @param chatId - The ID of the conversation to retrieve.
   */
  async get(chatId: string): Promise<ConversationDetail> {
    const response = await this.client._request("GET", `/api/v1/chat/${chatId}`);
    const data = await response.json();

    const messages: Message[] = (data.messages || []).map(
      (m: Record<string, unknown>) => ({
        role: m["role"],
        content: m["content"],
        timestamp: m["timestamp"] || null,
      })
    );

    return {
      chatId: data.chat_id || chatId,
      title: data.title || "",
      createdAt: data.created_at || null,
      lastActivity: data.last_activity || null,
      messageCount: messages.length,
      messages,
    };
  }

  /**
   * Delete a conversation.
   *
   * @param chatId - The ID of the conversation to delete.
   */
  async delete(chatId: string): Promise<boolean> {
    const response = await this.client._request("DELETE", `/api/v1/chat/${chatId}`);
    const data = await response.json();
    return data.success ?? false;
  }
}
