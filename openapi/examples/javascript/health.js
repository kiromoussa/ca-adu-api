// GET /v1/health - service liveness, uptime, API/rules versions, and
// non-sensitive source freshness. No authentication required, not billed.
//
// Run with: node health.js
async function main() {
  // No auth headers required for /health, on either host.
  const res = await fetch("https://api.aduatlas.example.com/v1/health");
  const health = await res.json();

  console.log(`status: ${health.status} (api ${health.api_version})`);
  for (const source of health.sources || []) {
    console.log(`  ${source.key}: ${source.data_status}`);
  }

  // Also reachable through the RapidAPI gateway (the Hub-registered path
  // has no /v1 prefix); still no auth headers required.
  await fetch("https://property-feasibility4.p.rapidapi.com/health");
}

main();
