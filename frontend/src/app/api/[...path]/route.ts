import { NextRequest, NextResponse } from 'next/server';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, await params);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, await params);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, await params);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, await params);
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, await params);
}

async function proxyRequest(
  request: NextRequest,
  params: { path: string[] }
) {
  const backendHost = process.env.GENDB_BACKEND_HOST || 'localhost';
  const path = params.path.join('/');
  const searchParams = request.nextUrl.searchParams.toString();
  const backendUrl = `http://${backendHost}:8000/${path}${searchParams ? `?${searchParams}` : ''}`;

  try {
    let body: string | ArrayBuffer | undefined = undefined;
    
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      const contentType = request.headers.get('content-type') || '';
      
      // For file uploads (multipart/form-data), preserve binary data
      if (contentType.includes('multipart/form-data')) {
        body = await request.arrayBuffer();
      } else {
        // For JSON and other text-based content, use text
        body = await request.text();
      }
    }

    const headers = new Headers();
    
    // Copy relevant headers from the original request
    for (const [key, value] of request.headers.entries()) {
      if (!key.toLowerCase().startsWith('host') && 
          !key.toLowerCase().startsWith('x-forwarded') &&
          !key.toLowerCase().startsWith('x-real-ip')) {
        headers.set(key, value);
      }
    }

    const response = await fetch(backendUrl, {
      method: request.method,
      headers,
      body,
    });

    const responseBody = await response.text();
    const responseHeaders = new Headers();
    
    // Copy response headers
    for (const [key, value] of response.headers.entries()) {
      if (!key.toLowerCase().startsWith('transfer-encoding') &&
          !key.toLowerCase().startsWith('connection')) {
        responseHeaders.set(key, value);
      }
    }

    return new NextResponse(responseBody, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error('Proxy error:', error);
    return NextResponse.json(
      { error: 'Failed to proxy request' },
      { status: 500 }
    );
  }
}