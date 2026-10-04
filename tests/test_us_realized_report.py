import pytest
from clawock.market_data.us_analysis import print_report, print_wechat_report


@pytest.mark.parametrize('amount,sign', [(2375.84, '+$'), (-1234.5, '$-'), (0, '+$')])
@pytest.mark.parametrize('printer', [print_report, print_wechat_report])
def test_realized_report_uses_amount_sign(capsys, amount, sign, printer):
    printer({'portfolios': {'us_stocks': {'realized_pnl': amount}}}, [])
    output = capsys.readouterr().out
    assert '+$-' not in output
    if amount or printer is print_report:
        line = next(line for line in output.splitlines() if '已实现' in line)
        assert sign in line
