// GET /v1/health - service liveness, uptime, API/rules versions, and
// non-sensitive source freshness. No authentication required, not billed.
//
// Run with: node health.js
async function main() {
  // No auth headers required for /v1/health, on either host.
  const res = await fetch("https://api.aduatlas.example.com/v1/health");
  const health = await res.json();

  console.log(`status: ${health.status} (api ${health.api_version})`);
  for (const source of health.sources || []) {
    console.log(`  ${source.key}: ${source.data_status}`);
  }
}

main();
