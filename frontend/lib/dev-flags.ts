export function isDirectConnectorDevEnabled(): boolean {
  return process.env.NEXT_PUBLIC_OPENRAG_ENABLE_DIRECT_CONNECTOR_DEV === "true";
}
