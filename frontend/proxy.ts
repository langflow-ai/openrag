import { type NextRequest, NextResponse } from "next/server";

export function proxy(request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  // Every inbound path except the dev-only HMR socket.
  matcher: ["/((?!_next/webpack-hmr).*)"],
};
