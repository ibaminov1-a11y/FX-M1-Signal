from pathlib import Path

p = Path('app/src/main/java/com/openai/fxm1/MainActivity.java')
s = p.read_text(encoding='utf-8')

old = '''    private void setTradingControlsOffline() {
        serverConnected = false;
        mt5Connected = false;
        demoAccount = false;
        serverStatusText.setText("SERVER: NOT CONNECTED   •   MT5: OFFLINE");
        serverStatusText.setTextColor(C_RED);
        if (whyWaitText != null) whyWaitText.setTextColor(C_ORANGE);
        if (componentScoresText != null) componentScoresText.setTextColor(C_PURPLE);
        if (smartStatusText != null) smartStatusText.setTextColor(C_MUTED);
        if (statsText != null) statsText.setTextColor(C_TEXT);
        if (signalHistoryText != null) signalHistoryText.setTextColor(C_MUTED);
        accountText.setText("Счёт: —\\nБаланс: —\\nEquity: —");
        positionsText.setText("Открытые позиции: —\\nТекущий P/L: —\\nСегодня: —\\nВсего: —");
        lastMt5Bid = Double.NaN;
        lastMt5Ask = Double.NaN;
        updatePriceComparison();
        closeAllButton.setEnabled(false);
        forceAutoOff(null);
    }
'''
new = '''    private void setTradingControlsOffline() {
        serverConnected = false;
        mt5Connected = false;
        demoAccount = false;
        serverStatusText.setText("SERVER: NOT CONNECTED   •   MT5: OFFLINE");
        serverStatusText.setTextColor(C_RED);
        if (whyWaitText != null) whyWaitText.setTextColor(C_ORANGE);
        if (componentScoresText != null) componentScoresText.setTextColor(C_PURPLE);
        if (smartStatusText != null) smartStatusText.setTextColor(C_MUTED);
        if (statsText != null) statsText.setTextColor(C_TEXT);
        if (signalHistoryText != null) signalHistoryText.setTextColor(C_MUTED);
        accountText.setText("Счёт: —\\nБаланс: —\\nEquity: —");
        positionsText.setText("Открытые позиции: —\\nТекущий P/L: —\\nСегодня: —\\nВсего: —");
        lastMt5Bid = Double.NaN;
        lastMt5Ask = Double.NaN;
        updatePriceComparison();
        closeAllButton.setEnabled(false);

        // Phone-side connectivity is NOT authority to change Bridge trading state.
        // A brief Wi-Fi/mobile handoff or Activity recreation must never send DISABLE.
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        boolean lastKnownAuto = p.getBoolean("auto_trading", false);
        suppressAutoSwitch = true;
        autoTradingSwitch.setChecked(lastKnownAuto);
        autoTradingSwitch.setEnabled(false);
        suppressAutoSwitch = false;
        if (autoStatusText != null) {
            autoStatusText.setText(lastKnownAuto
                    ? "Связь потеряна · последнее состояние AUTO: включён · Bridge не изменён"
                    : "Связь потеряна · последнее состояние AUTO: выключен · Bridge не изменён");
            autoStatusText.setTextColor(C_YELLOW);
        }
    }
'''
if old not in s:
    raise SystemExit('setTradingControlsOffline source pattern not found')
s = s.replace(old, new, 1)

old2 = '''            suppressAutoSwitch = true;
            boolean targetAllowed = "REAL".equals(targetTradeMode()) ? (!demoAccount && realTradingEnabled) : demoAccount;
'''
new2 = '''            autoTradingSwitch.setEnabled(true);
            suppressAutoSwitch = true;
            boolean targetAllowed = "REAL".equals(targetTradeMode()) ? (!demoAccount && realTradingEnabled) : demoAccount;
'''
if old2 not in s:
    raise SystemExit('online AUTO restore source pattern not found')
s = s.replace(old2, new2, 1)

p.write_text(s, encoding='utf-8')
