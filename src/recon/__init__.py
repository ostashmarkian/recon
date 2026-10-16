"""recon - look a website over before you scrape it.

    from recon import Recon, report
    findings = asyncio.run(Recon("https://www.example.com").run())
    print(report(findings))

Or, from a shell: recon https://www.example.com (see recon.cli).
"""

__version__ = "1.1.0"

from .probe import Recon
from .report import report

__all__ = ["Recon", "__version__", "report"]
