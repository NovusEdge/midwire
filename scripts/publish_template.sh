#!/usr/bin/env bash
# Publishes TEMPLATE.md as the Railway template's overview. Railway keeps its
# own copy and never reads the repo's. The template's variables are outside
# templatePublish and stay in Railway's template editor.
#
# Uses the Railway CLI login, or RAILWAY_API_TOKEN (an account token) in CI.
set -euo pipefail

TEMPLATE_ID=a3175849-d336-494b-8ceb-a97985b3c12a
WORKSPACE_ID=e56d8ef2-3a21-49a2-ae9e-20caaca0855d

cd "$(dirname "$0")/.."
vars=$(mktemp)
trap 'rm -f "$vars"' EXIT

jq -n --rawfile readme TEMPLATE.md \
  --arg id "$TEMPLATE_ID" --arg workspace "$WORKSPACE_ID" \
  '{id: $id, input: {
      category: "Other",
      description: "Verify your agent'"'"'s writes actually landed",
      readme: $readme,
      workspaceId: $workspace}}' > "$vars"

railway api 'mutation ($id: String!, $input: TemplatePublishInput!) {
  templatePublish(id: $id, input: $input) { id status }
}' --variables "@$vars"
