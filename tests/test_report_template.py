import unittest

from main import REPORT_TEMPLATE_NAME, TEMPLATE_DIR, build_report


class BuildReportTemplateTest(unittest.TestCase):
    def test_default_report_template_is_external_file(self):
        template_path = TEMPLATE_DIR / REPORT_TEMPLATE_NAME

        self.assertTrue(template_path.is_file())
        self.assertEqual(template_path.name, 'report.txt.j2')

    def test_build_report_renders_template_sections_and_optional_lines(self):
        scan_output = {
            'scan_date': '2026-04-14',
            'candidates_analyzed': 2,
            'results': [
                {
                    'ticker': '2330.TW',
                    'name': '台積電',
                    'label': 'STRONG BUY',
                    'score': 7,
                    'source': '0050.TW',
                    'price': {'current': 812.5, 'change_1d_pct': 1.23},
                    'trend': {'macd_hist': 4.2},
                    'momentum': {'rsi14': 55.2, 'stoch_k': 62.1, 'stoch_d': 58.4},
                    'volume': {'ratio': 1.8, 'obv_trend': 'rising'},
                    'levels': {'S1': 790.0, 'R1': 830.0},
                    'news_summary': 'AI 需求維持強勁。',
                    'previously_recommended': True,
                    'times_recommended': 3,
                },
                {
                    'ticker': '2317.TW',
                    'name': '鴻海',
                    'label': 'BUY',
                    'score': 4,
                    'price': {'current': 155.0, 'change_1d_pct': -0.2},
                    'trend': {},
                    'momentum': {'rsi14': 39.0},
                    'volume': {},
                },
            ],
        }

        self.assertEqual(
            build_report(scan_output),
            (
                '📡 市場新機會掃描報告\n'
                '2026-04-14 · 分析 2 檔候選股票\n'
                '\n'
                '━━━━━━━━━━━━━━━━━━━━━━\n'
                '🏆 強力機會\n'
                '━━━━━━━━━━━━━━━━━━━━━━\n'
                '\n'
                '🟢 2330.TW 台積電 [STRONG BUY] 分數: 7/8 · 來源: 0050.TW\n'
                '現價: $812.5 (+1.2%)\n'
                'RSI: 55 | Stoch K62/D58 | 成交量: 1.8×均量\n'
                '✅ MACD 柱狀體為正、RSI 處於健康區間 (55)\n'
                '支撐: 790.0  阻力: 830.0\n'
                '📰 AI 需求維持強勁。\n'
                '🔁 已連續推薦 3 次\n'
                '\n'
                '━━━━━━━━━━━━━━━━━━━━━━\n'
                '👀 值得關注\n'
                '━━━━━━━━━━━━━━━━━━━━━━\n'
                '\n'
                '🟡 2317.TW 鴻海 [BUY] 分數: 4/8 · $155.0 (-0.2%) RSI 39\n'
                '技術面維持偏多\n'
                '\n'
                '━━━━━━━━━━━━━━━━━━━━━━\n'
                '*本報告僅供參考，非投資建議。來源：市場篩選器 + ETF 持倉。*\n'
            ),
        )

    def test_build_report_renders_empty_sections(self):
        scan_output = {
            'scan_date': '2026-04-14',
            'candidates_analyzed': 0,
            'results': [],
        }

        self.assertEqual(
            build_report(scan_output),
            (
                '📡 市場新機會掃描報告\n'
                '2026-04-14 · 分析 0 檔候選股票\n'
                '\n'
                '━━━━━━━━━━━━━━━━━━━━━━\n'
                '🏆 強力機會\n'
                '━━━━━━━━━━━━━━━━━━━━━━\n'
                '\n'
                '本次沒有達到 STRONG BUY 門檻的標的。\n'
                '\n'
                '━━━━━━━━━━━━━━━━━━━━━━\n'
                '👀 值得關注\n'
                '━━━━━━━━━━━━━━━━━━━━━━\n'
                '\n'
                '本次沒有達到 BUY 門檻的標的。\n'
                '\n'
                '━━━━━━━━━━━━━━━━━━━━━━\n'
                '*本報告僅供參考，非投資建議。來源：市場篩選器 + ETF 持倉。*\n'
            ),
        )


if __name__ == '__main__':
    unittest.main()
