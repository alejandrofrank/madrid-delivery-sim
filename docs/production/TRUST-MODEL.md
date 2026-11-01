# Production trust model

The public replay and the live system are separate Cloud Run services. The replay
serves reviewed, synthetic recordings and static assets. It has no database,
Secret Manager, inference, vector-search or live-service permissions. It accepts
only GET and HEAD; URL parameters select recorded frames, never execution.

The live API is private at both the Cloud Run IAM boundary and the application
boundary. Google-signed ID tokens must name the receiving service as their
audience. The application verifies signature, issuer, expiry, audience and verified
email, then matches the identity against explicit operator or agent allowlists.
Every path and HTTP method is covered, including new write routes and mounted
protocol servers. The sole unauthenticated application path is a content-free
GET/HEAD `/livez`; Cloud Run IAM still protects it from external callers.

Dispatcher, restaurant and customer-service workers have separate service
accounts and private services. A worker accepts only its own A2A role and the
configured caller identities. Agent Cards advertise HTTPS endpoints and Google
ID-token bearer authentication. Callers obtain short-lived ID tokens from attached
credentials, use the exact target service audience and reject discovery redirects.
The Authorization header reaches the application verifier; a separate
X-Serverless-Authorization header is used by Cloud Run. Tokens are never logged.

The runtime's verified identity provides coarse service authorization. Existing
SQL leases, scoped tools, order/role boundaries, budgets and immutable memory
revisions remain the authority for individual agent actions. A model response,
memory hit, Agent Card or caller-provided role cannot grant a permission.

Deployment federation must restrict the GitHub repository and owner by immutable
IDs, the main branch and the deployment workflow. The CI identity may upload images
to this application's repository and update only its pre-provisioned public replay
service. It may act as only the replay identity. It cannot wake an absent service,
read Terraform state, change the spending cap or promote the private workers. It does not
receive project-owner, IAM-admin, billing-admin or service-account-key creation
rights. Infrastructure changes require the separate Terraform operator.

Local development retains its existing loopback controls and in-process transport.
Production starts through `delivery.production:create_app`; explicitly selecting
live mode without an HTTPS audience and operator policy fails closed. The live
API also installs its boundary when its original module is started directly.

The public replay has been deployed and removed after verification. Private live
workers remain disabled: role-specific Cloud IAM is implemented, but the local
lab's dynamic SQL identity provisioning still needs a least-privilege controller
bootstrap. Do not place the database owner's DSN into runtime secrets or grant
runtime logins CREATEROLE, unrestricted role administration or blanket RLS bypass.
`live_ready=false` is the default until that boundary is implemented and qualified.

References: [Google agent authentication](https://docs.cloud.google.com/run/docs/ai/authenticate-agents)
and [deployment federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines).
