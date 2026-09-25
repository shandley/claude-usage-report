# claude-usage-report

A small script that summarizes your Claude Code usage from the session logs Claude Code keeps on your machine. I use it to compare usage across my lab when choosing Claude plans.

## Run it

You need Python 3 (already installed on macOS). Nothing else.

```bash
curl -O https://raw.githubusercontent.com/shandley/claude-usage-report/main/claude_usage_report.py
python3 claude_usage_report.py --name "Your Name"
```

It takes a few seconds. By default it covers the last 30 days; use `--days 60` for a longer window.

If you use Claude Code on more than one computer, run it on each one.

## What it reads, and what it doesn't

It reads the token counts that Claude Code records for each request in `~/.claude/projects/`. The output contains only numbers: tokens by model, active days, requests, usage-limit hits, and an estimated cost. It does not print your prompts, code, file contents, or project names, and it sends nothing anywhere. You can read the whole script in a couple of minutes.

## Example output

```
Claude Code usage report: Your Name
Window: last 30 days (generated 2026-09-25)
Active days: 19   Sessions: 142   Requests: 3850
Usage-limit hits: 2
API-equivalent cost: $277 total, $277 per 30 days

Model                   Input M Cache wr M Cache rd M  Output M    API $
opus-4-8                   0.02       6.40      180.5      1.20      160
sonnet-5                   0.04      12.50      310.0      2.10      114
haiku-4-5                  0.01       0.80        9.2      0.15        3

API-equivalent $ by week:
  2026-W35  $      58  (partial week)
  2026-W36  $      72
  2026-W37  $      49
  2026-W38  $      61
  2026-W39  $      37  (partial week)
```

## Reading the numbers

- **Usage-limit hits** counts the times Claude Code stopped because you reached your plan's limit (repeats within the same minute count once). Zero means your plan has room to spare. Several a month means you are at its ceiling.
- **API-equivalent cost** prices your tokens at Anthropic's public API list prices. It is not what you pay: a subscription costs far less than this for heavy users. It is useful for comparing people on different plans, and for estimating what the same work would cost if billed per token.
- **By model** shows where usage goes. Opus and Fable models use quota much faster than Sonnet or Haiku. Advisor calls and fallbacks are counted under the model that actually ran them, and fast mode and web searches are priced at their list rates.

The script does not know your plan's quota, since Anthropic does not publish quotas in tokens. Report which plan you are on alongside the output.

## For Handley lab members

Send me three things:

1. The full output of the script.
2. Which Claude plan you are on now.
3. Whether you also use Claude in the browser or desktop app heavily, since this script only sees Claude Code.

## Prices

List prices are hard-coded in `PRICES` near the top of the script and were checked on 2026-09-25 against [Anthropic's pricing page](https://platform.claude.com/docs/en/about-claude/pricing). Models without a price are listed at the end of the report and counted as $0.

## License

MIT
