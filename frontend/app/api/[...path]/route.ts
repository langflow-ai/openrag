import { NextRequest, NextResponse } from "next/server";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, await params);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, await params);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, await params);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, await params);
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, await params);
}

async function proxyRequest(request: NextRequest, params: { path: string[] }) {
  const backendHost = process.env.OPENRAG_BACKEND_HOST || "localhost";
  const backendSSL = process.env.OPENRAG_BACKEND_SSL || false;
  const path = params.path.join("/");
  const searchParams = request.nextUrl.searchParams.toString();
  let backendUrl = `http://${backendHost}:8000/${path}${searchParams ? `?${searchParams}` : ""}`;
  if (backendSSL) {
    backendUrl = `https://${backendHost}:8000/${path}${searchParams ? `?${searchParams}` : ""}`;
  }

  try {
    let body: string | ArrayBuffer | undefined = undefined;
    let willSendBody = false;

    if (request.method !== "GET" && request.method !== "HEAD") {
      const contentType = request.headers.get("content-type") || "";
      const contentLength = request.headers.get("content-length");

      // For file uploads (multipart/form-data), preserve binary data
      if (contentType.includes("multipart/form-data")) {
        const buf = await request.arrayBuffer();
        if (buf && buf.byteLength > 0) {
          body = buf;
          willSendBody = true;
        }
      } else {
        // For JSON and other text-based content, use text
        const text = await request.text();
        if (text && text.length > 0) {
          body = text;
          willSendBody = true;
        }
      }

      // Guard against incorrect non-zero content-length when there is no body
      if (!willSendBody && contentLength) {
        // We'll drop content-length/header below
      }
    }

    const headers = new Headers();

    // Copy relevant headers from the original request
    for (const [key, value] of request.headers.entries()) {
      const lower = key.toLowerCase();
      if (
        lower.startsWith("host") ||
        lower.startsWith("x-forwarded") ||
        lower.startsWith("x-real-ip") ||
        lower === "content-length" ||
        (!willSendBody && lower === "content-type")
      ) {
        continue;
      }
      headers.set(key, value);
    }

    const init: RequestInit = {
      method: request.method,
      headers,
    };
    if (willSendBody) {
      // Convert ArrayBuffer to Uint8Array to satisfy BodyInit in all environments
      const bodyInit: BodyInit =
        typeof body === "string" ? body : new Uint8Array(body as ArrayBuffer);
      init.body = bodyInit;
    }
    const response = await fetch(backendUrl, init);

    const responseHeaders = new Headers();

    // Copy response headers
    for (const [key, value] of response.headers.entries()) {
      if (
        !key.toLowerCase().startsWith("transfer-encoding") &&
        !key.toLowerCase().startsWith("connection")
      ) {
        responseHeaders.set(key, value);
      }
    }

    // For streaming responses, pass the body directly without buffering
    if (response.body) {
      return new NextResponse(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } else {
      // Fallback for non-streaming responses
      const responseBody = await response.text();
      return new NextResponse(responseBody, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    }
  } catch (error) {
    console.error("Proxy error:", error);
    return NextResponse.json(
      { error: "Failed to proxy request" },
      { status: 500 },
    );
  }
}
