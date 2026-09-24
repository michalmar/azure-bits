# GPT-Live Azure infrastructure

`main.tf` uses AzureRM and AzAPI to create the dedicated Container Apps Express
hosting stack and a user-assigned identity. The existing Foundry account and
`gpt-live-1` deployment are **inputs**, never Terraform-managed resources.
Unlike a static media website, the demo stores no files, so it does not need
Blob Storage or an upload relay.

The first apply creates the foundation with no app image. After an ACR build,
a second apply creates a **locked** Container App that serves only `/healthz`.
`scripts/configure_entra.py` then discovers the generated HTTPS hostname,
creates or reuses the single-tenant Entra registration, stores its OAuth
credential as an encrypted Container Apps secret, and enables authenticated
reader routes. No anonymous bootstrap exposes the microphone demo.

The Terraform state is local at `infra/terraform.tfstate` and is intentionally
excluded from Git. Keep it in the authorized deployment workspace or back it
up through an approved secure process. If it is lost, restore or import the
existing resources before another apply; `scripts/deploy.sh` refuses to
recreate a resource group or app that exists outside its state.

Run `../scripts/deploy.sh` rather than applying only the app resource on
updates. Terraform does not manage the OAuth secret or live application
configuration after the initial locked bootstrap; the deploy script excludes
the existing app from foundation plans and performs a conditional ARM update
that preserves existing secrets. If an initial deployment stops after creating
the locked app, rerun the script with the original Terraform state to finish
configuring Entra sign-in.
