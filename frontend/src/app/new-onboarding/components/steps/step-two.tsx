"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { OnboardingStep } from "../onboarding-step";
import { Message } from "@/app/chat/types";
import { UserMessage } from "@/app/chat/components/user-message";
import { AssistantMessage } from "@/app/chat/components/assistant-message";

interface StepTwoProps {
  isVisible: boolean;
  isCompleted: boolean;
}

export function StepTwo({ isVisible, isCompleted }: StepTwoProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingMessage, setStreamingMessage] = useState<Message | null>(null);

  const handleAskAboutOpenRAG = async () => {
    setIsLoading(true);

    // Add user message
    const userMessage: Message = {
      role: "user",
      content: "What is OpenRAG?",
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);

    // Initialize streaming assistant message
    setStreamingMessage({
      role: "assistant",
      content: "",
      timestamp: new Date(),
      isStreaming: true,
    });

    try {
      const requestBody = {
        prompt: "What is OpenRAG?",
        stream: true,
        tweaks: {
          "Agent-crjWf": {
            system_prompt:
              `You are a helpful assistant that can use tools to answer questions and perform tasks.

If you're asked "What is OpenRAG?", respond with:

OpenRAG is an open-source package for building agentic RAG systems. It supports integration with a wide range of orchestration tools, vector databases, and LLM providers.

OpenRAG connects and amplifies three popular, proven open-source projects into one powerful platform:

- Langflow – A powerful tool to build and deploy AI agents and MCP servers.
- OpenSearch – Power your search apps with fast, scalable vector indexing.
- Docling – Flexible document ingestion and processing component for knowledge bases.

Together, these tools make it easy to build, connect, and deploy advanced Retrieval Augmented Generation (RAG) applications.
`
          },
        },
      };

      const res = await fetch("/api/onboarding-chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
      });

      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) {
        throw new Error("No reader available");
      }

      const decoder = new TextDecoder();
      let buffer = "";
      let fullResponse = "";

      console.log("Starting to read stream...");

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          console.log("Stream done");
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        console.log("Buffer updated, length:", buffer.length);
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        console.log("Processing", lines.length, "lines");
        for (const line of lines) {
          if (line.trim()) {
            console.log("Raw line:", line);
            try {
              const chunk = JSON.parse(line);
              console.log("Received chunk:", chunk);

              // Handle OpenAI Chat Completions streaming format
              if (chunk.object === "response.chunk" && chunk.delta?.content) {
                console.log("Adding content:", chunk.delta.content);
                fullResponse += chunk.delta.content;
                setStreamingMessage((prev) => prev ? { ...prev, content: fullResponse } : null);
                console.log("Full response now:", fullResponse);
              } else {
                console.log("Chunk did not match expected format");
              }
            } catch (e) {
              console.error("Error parsing chunk:", e, "Line:", line);
            }
          }
        }
      }
      console.log("Final response:", fullResponse);

      // Move streaming message to messages array
      if (streamingMessage && fullResponse) {
        setMessages((prev) => [...prev, { ...streamingMessage, content: fullResponse, isStreaming: false }]);
        setStreamingMessage(null);
      }
    } catch (error) {
      console.error("Error asking about OpenRAG:", error);
      // Add error message
      const errorMessage: Message = {
        role: "assistant",
        content: "Sorry, there was an error processing your request.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
      setStreamingMessage(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
      <OnboardingStep
        isVisible={isVisible}
        isCompleted={isCompleted}
        text="Excellent, let&apos;s move on to learning the basics. What would you like to read about?"
      >
        <div className="space-y-4">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleAskAboutOpenRAG}
            ignoreTitleCase
            disabled={isLoading}
            loading={isLoading}
          >
            What is OpenRAG?
          </Button>
        </div>
      </OnboardingStep>

      {/* Display messages */}
      {messages.map((message, index) => (
        <div key={index} className="mt-4">
          {message.role === "user" ? (
            <UserMessage content={message.content} />
          ) : (
            <AssistantMessage content={message.content} expandedFunctionCalls={new Set()} onToggle={() => {}} />
          )}
        </div>
      ))}

      {/* Display streaming message */}
      {streamingMessage && (
        <div className="mt-4">
          <AssistantMessage content={streamingMessage.content} expandedFunctionCalls={new Set()} onToggle={() => {}} />
        </div>
      )}
    </>
  );
}
