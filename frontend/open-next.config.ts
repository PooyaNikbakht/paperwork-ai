// OpenNext adapter config for Cloudflare Workers.
// Pages render in the browser and talk to the API directly, so no incremental cache is needed.
import { defineCloudflareConfig } from "@opennextjs/cloudflare";

export default defineCloudflareConfig({});
