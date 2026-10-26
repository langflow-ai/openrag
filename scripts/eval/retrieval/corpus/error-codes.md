# Error code reference

Relaywise error codes have the form `RW-` followed by four digits. The first digit tells you which part of the system reported the problem. API responses include the code in the `error.code` field, and delivery attempts show it in the console next to the attempt.

## 1xxx: authentication and authorisation

**RW-1401: Invalid or revoked credentials.** The API key is missing, malformed, expired or revoked. Check that the `Authorization` header uses the `Bearer` scheme and that the key has not been revoked.

**RW-1403: Missing scope.** The key is valid but is not allowed to do this. The response names the scope that is needed. Create a key with that scope, or add the scope to the existing key.

**RW-1410: Wrong key type.** A test key was used against a live source, or an automation key was used to send events.

**RW-1440: Session expired.** The console session has ended. Log in again.

## 2xxx: configuration

**RW-2001: Source not found.** The source ID in the URL does not exist in this workspace, or it has been deleted.

**RW-2004: Insecure destination URL.** Destination URLs must use HTTPS. Plain HTTP is accepted only for `localhost` through the development tunnel.

**RW-2010: Filter syntax error.** The route filter could not be parsed. The response gives the position of the first character that was not understood.

**RW-2020: Route limit reached.** The workspace already has the maximum number of routes its plan allows.

**RW-2031: Destination URL not allowed.** The URL resolves to a private or reserved network address. Relaywise delivers only to public addresses unless a private link is set up.

## 3xxx: delivery

**RW-3001: Delivery timeout.** The endpoint did not answer within the configured timeout. The attempt is retried.

**RW-3002: TLS handshake failed.** The endpoint's certificate has expired, is self-signed, or does not match the hostname.

**RW-3003: DNS resolution failed.** The hostname of the destination could not be resolved.

**RW-3004: Connection refused.** Nothing was listening at the destination's address and port.

**RW-3010: Non-success response.** The endpoint answered with a status code outside the 2xx range. The status code is recorded with the attempt.

**RW-3410: Destination disabled.** The destination was disabled after failing continuously for five days, or was disabled by hand. Events go to the dead-letter queue without being attempted.

## 4xxx: limits

**RW-4130: Payload too large.** The event is bigger than 256 KB.

**RW-4131: Batch too large.** The batch request is bigger than 5 MB or contains more than 500 events.

**RW-4290: Rate limit exceeded.** The workspace is sending faster than its plan allows. Wait until the time given in the `Retry-After` header.

**RW-4291: Monthly quota exhausted.** The workspace has used all the events included in its plan and has a hard cap, or is on the Sandbox plan, which has no overage.

## 5xxx: transformations

**RW-5001: Transformation runtime error.** The transformation code threw an exception. The message and line number are shown with the event.

**RW-5002: Transformation timed out.** The code ran longer than the time allowed.

**RW-5003: Transformation output too large.** The transformed payload is over the size limit.

**RW-5004: Transformation returned an invalid value.** The function has to return an object, or `null` to drop the event.

## 6xxx: replay

**RW-6001: Event no longer available.** The event is older than the retention period and its payload has been deleted, so it cannot be replayed.

**RW-6002: Replay already running.** A bulk replay for this destination is still in progress. Wait for it to finish or cancel it.

## 7xxx: regions

**RW-7001: Region mismatch.** The request was sent to an ingest hostname in a different region from the one the workspace lives in.

## 9xxx: service errors

**RW-9000: Internal error.** Something went wrong on the Relaywise side. The request is safe to retry. If the error continues, contact support and quote the request ID from the `Relaywise-Request-Id` response header.

**RW-9003: Service temporarily unavailable.** Relaywise is shedding load or carrying out maintenance. Retry after the interval in the `Retry-After` header.
