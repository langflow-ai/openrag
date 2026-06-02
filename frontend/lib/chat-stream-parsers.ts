import type { FunctionCall, TokenUsage } from "@/app/chat/_types/types";

type Chunk = Record<string, unknown>;

function getDeltaText(delta: unknown): string {
  if (typeof delta === "string") {
    return delta;
  }
  if (delta && typeof delta === "object") {
    const d = delta as Chunk;
    if (typeof d.content === "string") {
      return d.content;
    }
    if (typeof d.text === "string") {
      return d.text;
    }
  }
  return "";
}

export function parseOpenAIChatChunk(
  chunk: unknown,
  content: { value: string },
  calls: FunctionCall[],
): boolean {
  const c = chunk as Chunk;
  if (!(c.object === "response.chunk" && c.delta)) return false;

  const delta = c.delta as Chunk;

  if (delta.function_call) {
    const fc = delta.function_call as Chunk;
    if (fc.name) {
      calls.push({
        name: fc.name as string,
        arguments: undefined,
        status: "pending",
        argumentsString: (fc.arguments as string) || "",
      });
    } else if (fc.arguments) {
      const last = calls[calls.length - 1];
      if (last) {
        last.argumentsString =
          (last.argumentsString ?? "") + (fc.arguments as string);
        if (last.argumentsString.includes("}")) {
          try {
            last.arguments = JSON.parse(last.argumentsString);
            last.status = "completed";
          } catch {
            // arguments not yet complete
          }
        }
      }
    }
  } else if (delta.tool_calls && Array.isArray(delta.tool_calls)) {
    for (const toolCall of delta.tool_calls as Chunk[]) {
      const fn = toolCall.function as Chunk | undefined;
      if (!fn) continue;
      if (fn.name) {
        calls.push({
          name: fn.name as string,
          arguments: undefined,
          status: "pending",
          argumentsString: (fn.arguments as string) || "",
        });
      } else if (fn.arguments) {
        const idx =
          typeof toolCall.index === "number"
            ? (toolCall.index as number)
            : undefined;
        let target: FunctionCall | undefined;
        if (idx === undefined) {
          target = calls[calls.length - 1];
        } else if (idx >= 0 && idx < calls.length) {
          target = calls[idx];
        }
        if (target) {
          target.argumentsString =
            (target.argumentsString ?? "") + (fn.arguments as string);
          if (target.argumentsString.includes("}")) {
            try {
              target.arguments = JSON.parse(target.argumentsString);
              target.status = "completed";
            } catch {
              // arguments not yet complete
            }
          }
        }
      }
    }
  } else if (delta.content) {
    content.value += delta.content as string;
  }

  if (delta.finish_reason) {
    for (const fc of calls) {
      if (fc.status === "pending" && fc.argumentsString) {
        try {
          fc.arguments = JSON.parse(fc.argumentsString);
          fc.status = "completed";
        } catch {
          fc.arguments = { raw: fc.argumentsString };
          fc.status = "error";
        }
      }
    }
  }

  return true;
}

export function parseRealtimeChunk(
  chunk: unknown,
  content: { value: string },
  calls: FunctionCall[],
  usage: { value: TokenUsage | undefined },
): boolean {
  const c = chunk as Chunk;
  const type = c.type as string | undefined;
  if (!type) return false;

  const item = c.item as Chunk | undefined;

  if (type === "response.output_item.added" && item?.type === "function_call") {
    let existing = calls.find((fc) => fc.id === item.id);
    if (!existing) {
      existing = [...calls]
        .reverse()
        .find(
          (fc) =>
            fc.status === "pending" &&
            !fc.id &&
            fc.name === (item.tool_name || item.name),
        );
    }
    if (existing) {
      existing.id = item.id as string;
      existing.type = item.type as string;
      existing.name = (item.tool_name || item.name || existing.name) as string;
      existing.arguments = (item.inputs || existing.arguments) as Record<
        string,
        unknown
      >;
    } else {
      calls.push({
        name: (item.tool_name || item.name || "unknown") as string,
        arguments: item.inputs as Record<string, unknown> | undefined,
        status: "pending",
        argumentsString: "",
        id: item.id as string,
        type: item.type as string,
      });
    }
    return true;
  }

  if (
    type === "response.output_item.added" &&
    typeof item?.type === "string" &&
    item.type.includes("_call") &&
    item.type !== "function_call"
  ) {
    let existing = calls.find((fc) => fc.id === item.id);
    if (!existing) {
      existing = [...calls]
        .reverse()
        .find(
          (fc) =>
            fc.status === "pending" &&
            !fc.id &&
            fc.name === (item.tool_name || item.name || item.type),
        );
    }
    if (existing) {
      existing.id = item.id as string;
      existing.type = item.type as string;
      existing.name = (item.tool_name ||
        item.name ||
        item.type ||
        existing.name) as string;
      existing.arguments = (item.inputs || existing.arguments) as Record<
        string,
        unknown
      >;
    } else {
      calls.push({
        name: (item.tool_name || item.name || item.type || "unknown") as string,
        arguments: (item.inputs || {}) as Record<string, unknown>,
        status: "pending",
        id: item.id as string,
        type: item.type as string,
      });
    }
    return true;
  }

  if (type === "response.output_item.done" && item?.type === "function_call") {
    const functionCall = calls.find(
      (fc) =>
        fc.id === item.id ||
        fc.name === item.tool_name ||
        fc.name === item.name,
    );
    if (functionCall) {
      functionCall.status = item.status === "completed" ? "completed" : "error";
      functionCall.id = item.id as string;
      functionCall.type = item.type as string;
      functionCall.name = (item.tool_name ||
        item.name ||
        functionCall.name) as string;
      functionCall.arguments = (item.inputs ||
        functionCall.arguments) as Record<string, unknown>;
      if (item.results)
        functionCall.result = item.results as FunctionCall["result"];
    }
    return true;
  }

  if (
    type === "response.output_item.done" &&
    typeof item?.type === "string" &&
    item.type.includes("_call") &&
    item.type !== "function_call"
  ) {
    const functionCall = calls.find(
      (fc) =>
        fc.id === item.id ||
        fc.name === item.tool_name ||
        fc.name === item.name ||
        fc.name === item.type ||
        fc.name.includes((item.type as string).replace("_call", "")) ||
        (item.type as string).includes(fc.name),
    );
    if (functionCall) {
      functionCall.arguments = (item.inputs ||
        functionCall.arguments) as Record<string, unknown>;
      functionCall.status = item.status === "completed" ? "completed" : "error";
      functionCall.id = item.id as string;
      functionCall.type = item.type as string;
      if (item.results)
        functionCall.result = item.results as FunctionCall["result"];
    } else {
      calls.push({
        name: (item.tool_name || item.name || item.type || "unknown") as string,
        arguments: (item.inputs || {}) as Record<string, unknown>,
        status: "completed",
        id: item.id as string,
        type: item.type as string,
        result: item.results as FunctionCall["result"],
      });
    }
    return true;
  }

  if (type === "response.output_text.delta") {
    content.value += getDeltaText(c.delta);
    return true;
  }

  if (type === "response.completed" && (c.response as Chunk)?.usage) {
    usage.value = (c.response as Chunk).usage as TokenUsage;
    return true;
  }

  return false;
}

export function parseOpenRAGChunk(
  chunk: unknown,
  content: { value: string },
): boolean {
  const c = chunk as Chunk;

  if (c.output_text) {
    content.value += c.output_text as string;
    return true;
  }

  if (c.delta) {
    const deltaText = getDeltaText(c.delta);
    if (deltaText) {
      content.value += deltaText;
      return true;
    }
  }

  return false;
}

// Granite 3.3 8b workaround: detects implicit tool calls with no explicit tool call markers
export function detectImplicitToolCall(
  chunk: unknown,
  calls: FunctionCall[],
): void {
  if (calls.length > 0) return;

  const c = chunk as Chunk;

  const toolRelatedKeys = Object.keys(c).filter(
    (key) =>
      key.toLowerCase().includes("tool") ||
      key.toLowerCase().includes("call") ||
      key.toLowerCase().includes("retrieval") ||
      key.toLowerCase().includes("function") ||
      key.toLowerCase().includes("result"),
  );
  if (toolRelatedKeys.length > 0) {
    console.log(
      "[Tool Detection] Found tool-related keys:",
      toolRelatedKeys,
      chunk,
    );
  }

  const data = c.data as Chunk | undefined;

  const nonEmpty = (v: unknown): v is unknown[] =>
    Array.isArray(v) && (v as unknown[]).length > 0;

  const hasImplicitToolCall =
    nonEmpty(c.results) ||
    nonEmpty(c.outputs) ||
    nonEmpty(c.retrieved_documents) ||
    nonEmpty(c.retrieval_results) ||
    (data &&
      (nonEmpty(data.results) ||
        nonEmpty(data.retrieved_documents) ||
        nonEmpty(data.retrieval_results)));

  if (!hasImplicitToolCall) return;

  console.log("[Heuristic Detection] Detected implicit tool call:", chunk);
  const results =
    (nonEmpty(c.results) && c.results) ||
    (nonEmpty(c.outputs) && c.outputs) ||
    (nonEmpty(c.retrieved_documents) && c.retrieved_documents) ||
    (nonEmpty(c.retrieval_results) && c.retrieval_results) ||
    (nonEmpty(data?.results) && data?.results) ||
    (nonEmpty(data?.retrieved_documents) && data?.retrieved_documents) ||
    [];

  calls.push({
    name: "Retrieval",
    arguments: { implicit: true, detected_heuristically: true },
    status: "completed",
    type: "retrieval_call",
    result: results as FunctionCall["result"],
  });
  console.log("[Heuristic Detection] Created synthetic function call");
}

// Post-processing: detects RAG usage from citation/content patterns in final response text
export function detectRAGFromContent(content: string): FunctionCall | null {
  const hasCitations =
    /\(Source:|\[Source:|\bSource:|filename:|document:/i.test(content);
  const hasRAGPattern =
    /based on.*(?:document|file|information|data)|according to.*(?:document|file)/i.test(
      content,
    );

  if (!hasCitations && !hasRAGPattern) return null;

  console.log("[Post-Processing] Detected RAG usage from content patterns");
  return {
    name: "Retrieval",
    arguments: {
      implicit: true,
      detected_from: hasCitations ? "citations" : "content_patterns",
    },
    status: "completed",
    type: "retrieval_call",
  };
}
