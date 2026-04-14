# UX & PNL Analysis Design Spec

## 1. Overview
This specification details the improvements to the Telegram Bot's User Experience (UX) and the implementation of a true PNL (Profit and Loss) analysis feature. It transforms the current text-command bot into an interactive, dashboard-driven application using Telegram's Inline Keyboards.

## 2. Architecture & Data Flow (PNL Analysis)
- **Data Source**: The bot will fetch historical swap orders from the Ave Cloud API (`/v1/thirdParty/tx/getSwapOrder`).
- **Calculation Logic**: 
  - For each token, aggregate the total `inAmount` (USDT invested) and total `outAmount` (Tokens received).
  - Calculate the **Average Buy Price** (`Total USDT / Total Tokens`).
  - Fetch the **Current Price** of each token via Ave's token endpoints.
  - Calculate **PNL** as `(Current Price - Average Buy Price) / Average Buy Price * 100`.
- **Display**: PNL will be formatted as `+$15.00 (+10.5%)` or `-$5.00 (-2.3%)` per token, alongside the total portfolio PNL.

## 3. Components (Dashboard UX)
- **Main Menu (`/start`)**:
  - Serves as the "Home Screen".
  - If the user has no wallet, displays a `[Create Wallet]` button.
  - If registered, displays: 
    - `[My Portfolio]`
    - `[Trade]`
    - `[Deposit]`
    - `[Withdraw]`
    - `[Scan Signals]`
    - `[Smart Money Wallets]`
    - `[Help]`
- **Portfolio View (`/balance` or `[My Portfolio]`)**:
  - Replaces the current static text output.
  - Edits the existing message to show the PNL breakdown.
  - Includes buttons: `[Refresh]`, `[Trade Token]`, `[Back to Menu]`.
- **Trade, Deposit, Withdraw Flows**:
  - `[Deposit]` shows the user's BSC address and QR code.
  - `[Withdraw]` prompts the user for amount and destination address (interactive state).
  - `[Trade]` initiates a buy/sell flow with inline buttons for selecting tokens and confirming quotes.
- **Callback Handler**:
  - A new `CallbackQueryHandler` in `signal_telegram.py` will route button clicks (e.g., `cb_portfolio`, `cb_signals`, `cb_menu`) to their respective async functions.

## 4. Error Handling
- **API Failures**: If Ave API rate limits are hit or a price is unavailable, the bot will display a graceful "Fetching... please wait" or a fallback error message with a `[Retry]` button.
- **Empty States**: Clear messaging for users with no swap history (e.g., "No trades yet. Use `[Scan Signals]` to find your first trade!").

## 5. Implementation Steps
1. Refactor `cmd_start` to send an InlineKeyboardMarkup.
2. Create `callback_handler` to intercept button presses.
3. Update the balance/portfolio logic to calculate average buy prices and PNL.
4. Update `cmd_signal`, `cmd_topwallets`, and others to support callback queries and return "Back to Menu" buttons.
5. Test all interactive flows.
