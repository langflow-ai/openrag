# Troubleshooting

This page starts from what you can see going wrong and works back to a likely cause. Each section points to the page that covers the topic in full.

## My endpoint is not receiving anything

Work through the path an event takes.

1. **Was the event accepted?** Look for it under **Events**. If it is not there, the problem is on the sending side: check the response your sender got when it posted the event.
2. **Did it match a route?** An event marked **unrouted** was accepted but matched no route. Check the route's filter for a misspelled field name.
3. **Is the destination enabled?** A destination that is paused or disabled receives nothing. Its status is shown at the top of its page.
4. **Were attempts made?** Open the event and read the attempts. The status code or error on each attempt tells you what your endpoint did.

## Deliveries fail with a timeout

Your endpoint took longer than the timeout to answer. The usual cause is doing the real work before responding. Acknowledge the event first, then process it in the background. If the endpoint truly needs more time, raise the timeout on the destination.

## Deliveries fail with a 401 or 403

Your endpoint is turning Relaywise away. If you verify signatures, the secret your endpoint holds may be out of date, or the code may be checking a parsed body in place of the raw one. If your endpoint expects a token in a header, check the custom headers set on the destination.

## Deliveries fail with a certificate error

The certificate on your endpoint has expired, does not cover the hostname, or was issued by an authority that is not publicly trusted. Relaywise does not offer a way to skip certificate checks. Renew or replace the certificate.

## Every signature check fails

Three causes account for nearly all cases: the endpoint is using the secret of a different destination, the body was altered by a framework before the check, or the server's clock is more than a few minutes out.

## The same event arrives more than once

This is expected now and then. A delivery whose response was lost on the way back is retried even though your endpoint handled it. Record the event ID from the delivery headers and skip IDs you have seen. If duplicates are frequent, check whether two routes send the same event to the same destination.

## Events arrive out of order

Order is not guaranteed unless ordered delivery is switched on for the route. Either turn it on with a suitable ordering key, or make your endpoint compare a timestamp or version number in the payload before applying a change.

## My sender is getting 429 responses

You are sending faster than your plan allows. Slow down, wait for the time given in the response headers, and consider batching. If the response says the monthly quota is used up, waiting will not help: raise the cap or upgrade.

## A destination was switched off by itself

Relaywise disables a destination that has failed without a break for several days and emails the Admins. Fix the endpoint, re-enable the destination, then replay what collected in its dead-letter queue.

## A replay says the event is no longer available

The payload is older than the workspace's payload retention and has been deleted. The metadata may still be listed, but there is nothing left to send. Longer retention or a scheduled export prevents this in future.

## A transformation worked in the editor but fails on real events

Real events vary more than the sample you tested with. A field that is missing or null is the usual culprit. Open a failed event from the dead-letter queue, copy its payload into the editor, and run it there to see the exception.

## I cannot log in

If your workspace requires single sign-on, the password form will not accept you; use the **Log in with SSO** button. If single sign-on itself fails, ask a workspace Owner, who can still log in with a password. If you have lost your second factor, an Admin can reset it for you.

## The command-line tool says I am not signed in

A stored login lasts 30 days. Run `rwctl login` again. In a pipeline, check that the environment variable holding the key is set and that the key has not been revoked.

## Contacting support

When you write to support, include the workspace name, the event ID or destination ID, the time of the problem with its time zone, and the request ID from the response headers if you have one. These let support find the exact request without asking you for more.
