# BaseLodge Production Incident Alert Policy

**Status:** Policy and prerequisites only. Custom alerts are inactive.

This policy defines the smallest useful Production alert strategy after BL-178. Individual log events are diagnostic signals, not an incident system. Native Replit availability monitoring can be used now; custom error, performance, and provider alerts require the activation gate below.

## Signals available today

### Reliable Production signals

- Replit native monitoring provides uptime, request count, HTTP status, request duration, CPU, and memory views for the published Autoscale deployment. When enabled, it can send downtime email notifications.
- Replit deployment logs capture application stdout/stderr from the Gunicorn workers, including BL-178 structured events and process failures visible in the logs.
- BL-178 emits one `request_error` event for an unhandled application error and thresholded `request_slow` events for requests at or above 1000 ms. Events contain a request ID, normalized endpoint/route, HTTP method, status, duration, environment, severity, and exception class for errors.
- Every response includes `X-Request-ID`, allowing an operator to correlate a response with its structured log event.
- `/health` checks database connectivity and exposes the runtime environment and release identity status. A verified release SHA is available there when the deployment build metadata is valid.
- Message and push delivery paths expose provider acceptance/failure diagnostics, and message delivery outcomes are retained for administrative inspection.

### Important limitations

- BL-178 does not emit successful-request events or maintain counters, denominators, percentiles, grouping windows, alert state, cooldown state, or recovery state.
- Request events do not currently contain release identity. The health endpoint can identify the running release separately, but an event cannot independently prove which release produced it.
- There is no application boot/crash/restart event, restart counter, worker heartbeat, queue-depth signal, provider-outage aggregate, or automatic delivery alert.
- Provider acceptance does not prove device delivery. Existing provider logs are diagnostic and are not a safe incident payload by themselves.
- Traffic baselines have not been established. Every custom threshold in this document is **PROVISIONAL**.

## Severity model

### Critical

Immediate action is required: the deployment or health endpoint is unavailable, or a sustained high-volume application/provider failure indicates a likely outage.

### Warning

A sustained grouped error, route-performance, or provider pattern should be investigated soon but does not establish a total outage.

### Informational

Retain the signal for search and diagnosis without notifying anyone. This includes individual errors, individual slow requests, normal 404s, CSRF failures, 429 rate-limit responses, and isolated provider failures. Normal defensive responses must not page or notify an operator.

## Provisional custom alert policy

These rules must not be activated until the activation gate is satisfied. Group all rules by `environment` as well as the grouping key shown below.

| Incident | Provisional condition and window | Minimum volume | Grouping | Severity | Cooldown | Recovery |
|---|---|---:|---|---|---|---|
| Same error burst | At least 5 `request_error` events in 10 minutes | 5 errors | Normalized route + exception class | Warning | 60 minutes | Two consecutive 10-minute windows below threshold, with at least one qualifying request in each |
| Same error critical burst | At least 10 `request_error` events in 5 minutes | 10 errors | Normalized route + exception class | Critical | 15 minutes | Two consecutive 5-minute windows below threshold, with at least one qualifying request in each |
| Elevated overall 5xx rate | More than 2% over 10 minutes | At least 100 requests and 5 errors | All application requests | Warning | 60 minutes | Two consecutive 10-minute windows below threshold, with at least one qualifying request in each |
| Critical overall 5xx rate | More than 10% over 5 minutes | At least 50 requests and 10 errors | All application requests | Critical | 15 minutes | Two consecutive 5-minute windows below threshold, with at least one qualifying request in each |
| Sustained route slowness | More than 10% of one route's requests exceed 1000 ms over 15 minutes | At least 50 route requests and 10 slow events | Normalized route | Warning | 60 minutes | Two consecutive 15-minute windows below threshold and no severe-outlier condition |
| Severe repeated latency | At least 3 requests exceed 10 seconds in 5 minutes | 3 requests | Normalized route | Warning | 60 minutes | Two consecutive 15-minute windows without the condition |
| Provider degradation | More than 50% failed or channel-unavailable over 15 minutes | At least 20 attempts | Provider + normalized failure class | Warning | 60 minutes | Two consecutive 15-minute windows below threshold with the same minimum volume |
| Provider outage | More than 90% failed over 10 minutes | At least 20 attempts | Provider + normalized failure class | Critical only when the provider is business-critical | 15 minutes | Two consecutive 15-minute windows below threshold with the same minimum volume |

An alert opens once per group and updates its observed count/rate; it must not notify once per event. A severity increase may bypass the active cooldown once. After recovery, a later breach may open a new incident. Low or absent traffic is not recovery for a rate-based alert; mark the incident stale instead.

## Activation gate

Custom alerts **must not** be activated until all of the following are true:

1. At least 14 representative Production days exist.
2. At least 1,000 Production requests have been observed.
3. The provisional thresholds have been recalibrated against that baseline.
4. An independently approved aggregation and delivery service exists that can ingest safe events or metrics, calculate windows and denominators, group and deduplicate incidents, evaluate recovery, and deliver notifications independently of BaseLodge.

The Production baseline is a separate follow-up task; do not implement measurement in this policy. A custom aggregation/delivery service has not been selected. Provider alerts additionally require reliable attempt/failure aggregation and failure classification. Release-to-event correlation is a separate prerequisite: verified release SHA/status should be added to the structured event allowlist before custom alerts are activated.

## Native availability monitoring

Replit's documented deployment monitoring is the only alerting capability to use immediately:

1. Open the published deployment's **Publishing** tool and open its monitoring surface.
2. Enable app uptime monitoring for the Autoscale deployment.
3. Enable the available downtime email notification and confirm the intended operator address through the Publishing UI.
4. Verify that the monitoring surface reports the deployment as healthy and shows uptime/request metrics. Confirm that the published application and its health endpoint are reachable.
5. During an outage, use the monitoring status and deployment logs as the first source of truth. Do not add application-side notifications as a substitute.

These steps are operational settings only; BL-179 does not change `.replit`, deployment settings, or application code. See the current [Replit deployment monitoring documentation](https://docs.replit.com/features/publishing/monitoring-a-deployment) for the UI and availability details.

Replit monitoring and deployment logs do not provide documented configurable log-derived rules or webhook delivery for BL-178 JSON events. Until an independent service is approved, those events remain searchable diagnostics.

## Safe alert payload

An alert may contain only:

- environment
- severity and incident type
- normalized endpoint/route
- threshold and evaluation window
- observed count or rate
- one representative request ID
- exception class when relevant
- provider and normalized failure class when relevant
- verified release identity when available

Never include:

- user identity, email address, or IP address
- request contents or raw URL/query string
- headers or cookies
- credentials, secrets, or tokens
- raw exception messages
- provider payloads
- model objects or other sensitive application data

## Minimum response runbook

### Availability

Check Replit deployment status, native monitoring, and `/health` first. Inspect the deployment/build logs for process failures. Restart only when a process is stuck; investigate or roll back when the incident began immediately after a verified release and the logs implicate that release.

### Server errors

Search the structured logs using the representative request ID, normalized route, and exception class. Compare the health endpoint's release identity with deployment history, then determine whether the failure is isolated to one route or affects all traffic before restarting or rolling back.

### Performance degradation

Inspect route grouping, request volume, duration, database health, CPU, memory, and recent deployment timing. Do not restart for one slow request or treat low traffic as recovery.

### Provider degradation

Confirm an aggregate failure pattern and its classification before acting. Distinguish channel-unavailable recipients from a provider outage, check provider status, and avoid broad retries or broadcasts until the scope is known.

## Scope and prerequisites

This document is the complete BL-179 deliverable. It does not implement an alert engine, select or provision a vendor, add dashboards, add alert state, change BL-178, change provider logging, add a schema or migration, change secrets, touch persistent or Production data, or change deployment configuration.

Custom alerts remain inactive until the baseline, independent aggregation/delivery service, provider aggregation, and release-to-event correlation prerequisites are complete.
