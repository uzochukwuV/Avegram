# Avegram — Roadmap

## Product Vision
Telegram-native crypto platform combining AI signal generation, smart money tracking, and one-tap spot trading — all in one bot conversation.

## Current Build (v0.1)
- Telegram bot with 8 commands on BSC/Solana
- CLI scanner + trade preview tools
- ~1288 lines Python, Ave Cloud API (free plan)
- Hackathon-ready MVP

## Bugs — Fix Before Demo
- [ ] **Trade execution** — Quote works but execution needs RPC or Ave proxy wallet (upgrade API plan)
- [ ] **/signal** — Only scans 19 hardcoded keywords; replace with trending/new tokens endpoint
- [ ] **/balance** — Show per-token current price so users see $PnL
- [ ] **ETH chain** — Ave free plan doesn't support ETH walletinfo (paid plan or RPC fallback)

## v0.2 — Hackathon Demo (April 21)
- [ ] Demo video: register → deposit → /signal → /topwallets → /track → /trade quote
- [ ] Ave API plan upgrade to **normal** (unlocks proxy wallet, ETH, better rate limits)
- [ ] Replace keyword scan with trending/new token feed for /signal
- [ ] Get QuickNode or public RPC for BSC execution (or Ave proxy wallet)
- [ ] README polished with demo screenshots
- [ ] Hackathon submission form filled

## v0.3 — Feature Complete
- [ ] Full trade execution (proxy wallet or RPC signing)
- [ ] /signal with configurable confidence threshold
- [ ] /alert <token> — push notifications when signal triggers
- [ ] /history — all past signals + outcomes
- [ ] Multi-token portfolio view in USD across all chains
- [ ] Anti-rug/honeypot check built into every /trade execution

## v1.0 — Public Launch
### Trading
- [ ] Market + limit orders
- [ ] TP/SL automation via Ave proxy wallet
- [ ] DCA/recurring buy setup
- [ ] DEX aggregator routing (best price across 300+ DEXs)

### Signals
- [ ] Real-time WebSocket stream for smart money moves
- [ ] Whale wallet alert system (configurable threshold)
- [ ] Multi-timeframe signals (5m, 1h, 4h, 1d)
- [ ] Cross-chain signals (BSC, ETH, Solana, Base, Pump.fun)

### Monetization
- [ ] Subscription tiers: Free (3 signals/day) → Pro ($9.99/mo unlimited)
- [ ] Premium signals bundle (smart money copy-trades)
- [ ] Affiliate/referral commission on trading fees
- [ ] Token presale launchpad integration

### UX
- [ ] Persistent user sessions (not wallet-per-command)
- [ ] P&L tracking dashboard
- [ ] Copy-trading: follow top wallets with one tap
- [ ] Multi-language support (EN → 中文 → 其他)

## Technical
- [ ] Zo Computer hosting (current: manual process)
- [ ] Postgres DB for user state + signal history
- [ ] Redis cache for token prices
- [ ] Docker container for reproducibility
- [ ] Automated tests (pytest)
- [ ] CI/CD pipeline (GitHub Actions)

## Business
- [ ] Ave Cloud partner integration (revenue share on API usage)
- [ ] Telegram Mini App for non-bot UX
- [ ] Community: Discord server + X presence
- [ ] Blog: "How we detect smart money" (educational content)
