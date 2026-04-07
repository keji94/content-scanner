# Content Scanner Heartbeat

## Scan Schedule

### Daily Content Audit

- **Cron**: Every day, morning
- **Action**: Scan all content files listed in targets below
- **Mode**: full (Phase 1 + Phase 2)
- **Notify**: Only if score drops below B grade (score < 80) or has new critical violations

### Weekly Deep Scan

- **Cron**: Every Monday, morning
- **Action**: Full scan on all tracked content with complete Phase 2 analysis
- **Notify**: Always, with summary report including all grades and top issues

## Scan Targets

Configure per workspace. Each target specifies:

```yaml
targets:
  - path: "<content_file_path>"
    workspace: "<workspace_path>"
    genre: "<genre>"
    threshold:
      min_grade: "B"
      max_critical: 0
```

Add one entry per content file to track.

## Notification Rules

- **Always notify on**: new critical violations, grade drop of 2+ levels
- **Suppress if**: score >= threshold and no new violations
- **Delivery**: Chat message to originating channel

## Health Check

On each heartbeat tick, verify:

1. Python runtime available: `python3 --version`
2. Target content files exist
3. Workspace directories (rules/, context/) exist
4. Last scan completed successfully (no stale temp files)

If health check fails, notify user with specific error.
