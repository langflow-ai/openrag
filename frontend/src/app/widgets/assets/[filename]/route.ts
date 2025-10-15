import { NextRequest, NextResponse } from "next/server";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ filename: string }> }
) {
  const { filename } = await params;
  const backendHost = process.env.OPENRAG_BACKEND_HOST || "localhost";
  const backendPort = process.env.OPENRAG_BACKEND_PORT || "8000";
  const backendSSL = parseBoolean(process.env.OPENRAG_BACKEND_SSL);
  const protocol = backendSSL ? "https" : "http";
  const backendBaseUrl = `${protocol}://${backendHost}:${backendPort}`;

  try {
    // Forward the request to the backend
    const backendUrl = `${backendBaseUrl}/widgets/assets/${filename}`;
    const response = await fetch(backendUrl, {
      method: "GET",
      headers: {
        // Forward relevant headers
        ...Object.fromEntries(
          Array.from(request.headers.entries()).filter(([key]) =>
            ["accept", "accept-encoding", "user-agent"].includes(key.toLowerCase())
          )
        ),
      },
    });

    if (!response.ok) {
      return new NextResponse(null, { status: response.status });
    }

    // Get the content type from backend response
    const contentType = response.headers.get("content-type");
    const body = await response.arrayBuffer();

    // Return the response with appropriate headers
    return new NextResponse(body, {
      status: response.status,
      headers: {
        "Content-Type": contentType || "application/octet-stream",
        "Cache-Control": "public, max-age=3600",
      },
    });
  } catch (error) {
    console.error("Error proxying widget asset:", error);
    return new NextResponse("Internal Server Error", { status: 500 });
  }
}

function parseBoolean(value?: string | null): boolean {
  if (!value) {
    return false;
  }
  const normalized = value.toLowerCase();
  return normalized === "true" || normalized === "1" || normalized === "yes" || normalized === "on";
}
