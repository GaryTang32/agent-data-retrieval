# Inference Gateway Failover Runbook

Source: confluence

Owner: Platform Reliability. Use this runbook when the primary inference gateway stops serving requests in one region.

## Steps

1. Confirm the alert in the on-call dashboard and check that the gateway health check has failed for at least five minutes.
2. Page the secondary on-call engineer and open an incident channel named after the region.
3. Drain the failing region by setting its traffic weight to zero in the load balancer console.
4. Verify that the standby region serves requests with an error rate below one percent.
5. If the error rate stays above one percent for ten minutes, escalate to the Platform Reliability lead.
6. Record the timeline in the incident ticket and close the incident channel after the review.
