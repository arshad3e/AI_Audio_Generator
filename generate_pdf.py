from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.rl_config import defaultPageSize
from reportlab.platypus import PageTemplate, BaseDocTemplate, Frame
from reportlab.lib.enums import TA_CENTER, TA_LEFT

class MyDocTemplate(BaseDocTemplate):
    def __init__(self, filename, **kw):
        BaseDocTemplate.__init__(self, filename, **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id='normal')
        template = PageTemplate(id='standard', frames=frame, onPage=self.add_page_number)
        self.addPageTemplates([template])

    def add_page_number(self, canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 10)
        page_number = f"Page {doc.page}"
        footer = "© 2025 Arshad Shaik"
        canvas.drawCentredString(defaultPageSize[0]/2, 0.5*inch, footer)
        canvas.drawRightString(defaultPageSize[0] - inch, 0.5*inch, page_number)
        canvas.restoreState()

def create_pdf(output_file):
    # Setup document
    doc = MyDocTemplate(
        output_file,
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch
    )
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(name='Title', fontName='Helvetica-Bold', fontSize=28, spaceAfter=18, alignment=TA_CENTER)
    subtitle_style = ParagraphStyle(name='Subtitle', fontName='Helvetica', fontSize=16, spaceAfter=24, alignment=TA_CENTER)
    heading_style = ParagraphStyle(name='Heading', fontName='Helvetica-Bold', fontSize=14, spaceAfter=12)
    subheading_style = ParagraphStyle(name='Subheading', fontName='Helvetica-Bold', fontSize=12, spaceAfter=10)
    body_style = ParagraphStyle(name='Body', fontName='Helvetica', fontSize=11, spaceAfter=8, leading=14)
    list_style = ParagraphStyle(name='List', fontName='Helvetica', fontSize=11, spaceAfter=8, leading=14)

    # Content
    story = []

    # Cover page
    story.append(Paragraph("The Crypto Starter Kit", title_style))
    story.append(Paragraph("Your Essential Guide to Getting Started with Cryptocurrency", subtitle_style))
    story.append(PageBreak())

    # Introduction
    story.append(Paragraph("Introduction", heading_style))
    story.append(Paragraph(
        "Welcome to <i>The Crypto Starter Kit</i>! This guide is designed to help you navigate the world of cryptocurrency with confidence. "
        "Perfect for beginners and intermediate users, it provides:<br/>"
        "- Over 50 curated resources for trading, learning, and security<br/>"
        "- Step-by-step instructions for setting up wallets and exchanges<br/>"
        "- Best practices to protect your investments<br/>"
        "- Worksheets to plan and track your crypto journey<br/>"
        "Let’s unlock the potential of cryptocurrency!",
        body_style
    ))
    story.append(Spacer(1, 12))

    # Getting Started
    story.append(Paragraph("Getting Started with Crypto", heading_style))
    story.append(Paragraph("What is Cryptocurrency?", subheading_style))
    story.append(Paragraph(
        "Cryptocurrency is a digital or virtual currency secured by cryptography, operating on decentralized blockchain networks. "
        "Bitcoin is the most well-known, but thousands of others exist, each with unique features.",
        body_style
    ))
    story.append(Paragraph("Why Invest in Crypto?", subheading_style))
    story.append(ListFlowable([
        ListItem(Paragraph("Decentralization: No central authority controls it.", list_style), leftIndent=20),
        ListItem(Paragraph("Accessibility: Anyone with internet access can participate.", list_style), leftIndent=20),
        ListItem(Paragraph("Potential Returns: High volatility can lead to significant gains (and losses).", list_style), leftIndent=20)
    ], bulletType='bullet', start='•'))
    story.append(Paragraph("<b>Tip:</b> Research thoroughly before investing to understand risks.", body_style))
    story.append(Paragraph("Actionable Steps", subheading_style))
    story.append(ListFlowable([
        ListItem(Paragraph("Set up a wallet (see Wallets section).", list_style), leftIndent=20),
        ListItem(Paragraph("Choose a trusted exchange (see Exchanges section).", list_style), leftIndent=20),
        ListItem(Paragraph("Make a small first purchase to learn the process.", list_style), leftIndent=20),
        ListItem(Paragraph("Track your portfolio with a tool (see Portfolio Tracking section).", list_style), leftIndent=20)
    ], bulletType='1', start='1'))
    story.append(Spacer(1, 12))

    # Exchanges
    story.append(Paragraph("Cryptocurrency Exchanges", heading_style))
    story.append(Paragraph(
        "Exchanges are platforms where you can buy, sell, and trade cryptocurrencies. Here are top options:<br/>"
        "- <b>Coinbase</b>: Ideal for beginners. <i>Pros:</i> User-friendly, insured deposits. <i>Cons:</i> Higher fees. "
        "<a href='https://www.coinbase.com'>coinbase.com</a><br/>"
        "- <b>Binance</b>: Best for advanced users. <i>Pros:</i> Low fees, wide coin selection. <i>Cons:</i> Complex interface. "
        "<a href='https://www.binance.com'>binance.com</a><br/>"
        "- <b>Kraken</b>: Strong security features. <i>Pros:</i> Transparent, secure. <i>Cons:</i> Limited coin options. "
        "<a href='https://www.kraken.com'>kraken.com</a>",
        body_style
    ))
    story.append(Paragraph("<b>Tip:</b> Start with a small investment to test the platform.", body_style))
    story.append(Spacer(1, 12))

    # Wallets
    story.append(Paragraph("Wallets for Security", heading_style))
    story.append(Paragraph(
        "Wallets store your cryptocurrency assets. There are two main types:<br/>"
        "<b>Hardware Wallets (Offline):</b><br/>"
        "- <b>Ledger</b>: Ideal for long-term storage. <a href='https://www.ledger.com'>ledger.com</a><br/>"
        "- <b>Trezor</b>: Open-source and secure. <a href='https://trezor.io'>trezor.io</a><br/>"
        "<b>Software Wallets (Online):</b><br/>"
        "- <b>MetaMask</b>: Great for Ethereum and DeFi. <a href='https://metamask.io'>metamask.io</a><br/>"
        "- <b>Trust Wallet</b>: Supports multiple blockchains. <a href='https://trustwallet.com'>trustwallet.com</a>",
        body_style
    ))
    story.append(Paragraph("<b>Action:</b> Use a hardware wallet for large holdings to maximize security.", body_style))
    story.append(Spacer(1, 12))

    # Security
    story.append(Paragraph("Security Best Practices", heading_style))
    story.append(Paragraph(
        "Protect your crypto investments with these essential tips:",
        body_style
    ))
    story.append(ListFlowable([
        ListItem(Paragraph("Enable Two-Factor Authentication (2FA) on all accounts.", list_style), leftIndent=20),
        ListItem(Paragraph("Use a VPN like <b>NordVPN</b> for secure transactions. <a href='https://nordvpn.com'>nordvpn.com</a>", list_style), leftIndent=20),
        ListItem(Paragraph("Store wallet recovery phrases offline in a safe location.", list_style), leftIndent=20),
        ListItem(Paragraph("Avoid scams; never share private keys or recovery phrases.", list_style), leftIndent=20)
    ], bulletType='bullet', start='•'))
    story.append(Paragraph("<b>Worksheet:</b> Complete the Security Checklist in Appendix A.", body_style))
    story.append(Spacer(1, 12))

    # Portfolio Tracking
    story.append(Paragraph("Portfolio Tracking Tools", heading_style))
    story.append(Paragraph(
        "Monitor your crypto investments with these tools:<br/>"
        "- <b>CoinStats</b>: Real-time tracking across exchanges. <a href='https://coinstats.app'>coinstats.app</a><br/>"
        "- <b>Delta</b>: Sleek interface for portfolio management. <a href='https://delta.app'>delta.app</a><br/>"
        "- <b>Blockfolio</b>: Simple and effective tracking. <a href='https://blockfolio.com'>blockfolio.com</a>",
        body_style
    ))
    story.append(Paragraph("<b>Action:</b> Choose and set up one tracking tool.", body_style))
    story.append(Spacer(1, 12))

    # Educational Resources
    story.append(Paragraph("Educational Resources", heading_style))
    story.append(Paragraph(
        "Expand your crypto knowledge with these resources:<br/>"
        "- <b>Coin Bureau (YouTube)</b>: In-depth videos on crypto topics. <a href='https://www.youtube.com/c/CoinBureau'>youtube.com/c/CoinBureau</a><br/>"
        "- <b>Coursera Blockchain Courses</b>: Structured courses from top universities. <a href='https://www.coursera.org'>coursera.org</a><br/>"
        "- <b>Mastering Bitcoin</b> by Andreas Antonopoulos: Technical insights (available on Amazon).",
        body_style
    ))
    story.append(Paragraph("<b>Tip:</b> Dedicate 30 minutes daily to learning.", body_style))
    story.append(Spacer(1, 12))

    # News and Community
    story.append(Paragraph("News and Community", heading_style))
    story.append(Paragraph(
        "Stay informed and connected with the crypto community:<br/>"
        "- <b>CoinDesk</b>: Comprehensive crypto news. <a href='https://www.coindesk.com'>coindesk.com</a><br/>"
        "- <b>Reddit r/CryptoCurrency</b>: Active discussion forum. <a href='https://www.reddit.com/r/CryptoCurrency'>reddit.com/r/CryptoCurrency</a><br/>"
        "- <b>Discord Groups</b>: Search 'Crypto Discord' for real-time chats.",
        body_style
    ))
    story.append(Paragraph("<b>Action:</b> Join at least one community to stay updated.", body_style))
    story.append(Spacer(1, 12))

    # Common Mistakes
    story.append(Paragraph("Common Mistakes to Avoid", heading_style))
    story.append(ListFlowable([
        ListItem(Paragraph("FOMO Buying: Research thoroughly instead of chasing market hype.", list_style), leftIndent=20),
        ListItem(Paragraph("Ignoring Fees: High transaction fees can reduce profits.", list_style), leftIndent=20),
        ListItem(Paragraph("Neglecting Security: Always prioritize asset protection.", list_style), leftIndent=20)
    ], bulletType='bullet', start='•'))
    story.append(Paragraph("<b>Worksheet:</b> Create a trading plan using Appendix B.", body_style))
    story.append(Spacer(1, 12))

    # Appendices
    story.append(Paragraph("Appendix A: Security Checklist", heading_style))
    story.append(ListFlowable([
        ListItem(Paragraph("☐ Enable 2FA on all accounts.", list_style), leftIndent=20),
        ListItem(Paragraph("☐ Use a VPN for transactions.", list_style), leftIndent=20),
        ListItem(Paragraph("☐ Backup recovery phrases offline.", list_style), leftIndent=20),
        ListItem(Paragraph("☐ Update passwords regularly.", list_style), leftIndent=20)
    ], bulletType='bullet', start='☐'))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Appendix B: Trading Plan Template", heading_style))
    story.append(ListFlowable([
        ListItem(Paragraph("Goals: E.g., 10% annual return.", list_style), leftIndent=20),
        ListItem(Paragraph("Risk Tolerance: Amount you’re willing to lose.", list_style), leftIndent=20),
        ListItem(Paragraph("Strategy: Buy-and-hold, day trading, etc.", list_style), leftIndent=20),
        ListItem(Paragraph("Review Schedule: Weekly, monthly, etc.", list_style), leftIndent=20)
    ], bulletType='1', start='1'))
    story.append(Spacer(1, 12))

    # Build PDF
    doc.build(story)
    print(f"PDF generated: {output_file}")

if __name__ == "__main__":
    output_file = "The_Crypto_Starter_Kit.pdf"
    create_pdf(output_file)
