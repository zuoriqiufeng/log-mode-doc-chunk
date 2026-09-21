"""
创建包含文本、嵌入图片和表格的示例 PDF 文件。
使用 PIL 生成真实图片并嵌入 PDF，以便 pypdf 能提取。
"""
import io

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Table, TableStyle
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter


def create_sample_image() -> bytes:
    """使用 PIL 创建示例图片，返回 PNG 字节。"""
    img = Image.new("RGB", (400, 200), color=(230, 240, 255))
    draw = ImageDraw.Draw(img)

    # 绘制标题
    draw.text((20, 20), "Onyx Architecture", fill=(0, 50, 100))

    # 绘制简单框图
    boxes = [
        ((20, 60), (120, 100), "Frontend", (200, 220, 255)),
        ((160, 60), (260, 100), "API", (200, 255, 200)),
        ((300, 60), (380, 100), "Workers", (255, 220, 200)),
        ((20, 120), (120, 160), "Postgres", (255, 240, 200)),
        ((160, 120), (260, 160), "Redis", (240, 220, 255)),
        ((300, 120), (380, 160), "Vespa", (220, 255, 240)),
    ]

    for (x1, y1), (x2, y2), label, color in boxes:
        draw.rectangle([x1, y1, x2, y2], fill=color, outline=(100, 100, 100), width=2)
        # 居中文字
        bbox = draw.textbbox((0, 0), label)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((x1 + x2 - tw) // 2, (y1 + y2 - th) // 2), label, fill=(50, 50, 50))

    # 连接线
    draw.line([(120, 80), (160, 80)], fill=(100, 100, 100), width=2)
    draw.line([(260, 80), (300, 80)], fill=(100, 100, 100), width=2)
    draw.line([(70, 100), (70, 120)], fill=(100, 100, 100), width=2)
    draw.line([(210, 100), (210, 120)], fill=(100, 100, 100), width=2)
    draw.line([(340, 100), (340, 120)], fill=(100, 100, 100), width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_sample_pdf(output_path: str) -> None:
    """创建包含文本、嵌入图片和表格的示例 PDF。"""

    writer = PdfWriter()
    width, height = A4

    # ========== 第一页：文本 + 嵌入图片 ==========
    packet1 = io.BytesIO()
    c = canvas.Canvas(packet1, pagesize=A4)

    # 标题
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "Onyx Document Processing Demo")

    # 正文
    c.setFont("Helvetica", 11)
    y = height - 80
    for line in [
        "This document demonstrates PDF processing with text, images, and tables.",
        "",
        "Core Features:",
        "- Agentic RAG with hybrid indexing",
        "- Deep Research for comprehensive reports",
        "- Custom AI Agents with unique knowledge",
        "- Web Search integration (Serper, Brave, etc.)",
        "- Code Execution in sandboxed environments",
        "- Voice Mode with TTS and STT support",
        "- Image Generation from text prompts",
        "- 50+ Enterprise Connectors",
    ]:
        c.drawString(50, y, line)
        y -= 14

    # 嵌入真实图片（PIL 生成）
    img_bytes = create_sample_image()
    img_path = "/tmp/onyx_demo_img.png"
    with open(img_path, "wb") as f:
        f.write(img_bytes)
    c.drawImage(img_path, 50, y - 160, width=250, height=125)

    # 图片说明
    y -= 170
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(50, y, "Figure 1: Onyx system architecture diagram")
    c.setFont("Helvetica", 11)

    # 更多文本
    y -= 30
    for line in [
        "The Onyx platform connects to company documents, apps, and people.",
        "It provides RAG-based intelligent Q&A with advanced retrieval.",
        "",
        "Technology Stack:",
        "- Backend: Python 3.11, FastAPI, SQLAlchemy, Celery",
        "- Frontend: Next.js, React, TypeScript, Tailwind CSS",
        "- Database: PostgreSQL with Redis caching",
        "- Vector Search: Vespa vector database",
        "- LLM Integration: LiteLLM with multi-provider support",
    ]:
        c.drawString(50, y, line)
        y -= 14

    c.showPage()
    c.save()
    packet1.seek(0)
    page1 = PdfReader(packet1).pages[0]
    writer.add_page(page1)

    # ========== 第二页：表格 ==========
    packet2 = io.BytesIO()
    c = canvas.Canvas(packet2, pagesize=A4)

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 50, "Connector Comparison Table")

    c.setFont("Helvetica", 11)
    y = height - 80
    c.drawString(50, y, "The following table compares different connector types:")
    y -= 30

    # 使用 reportlab Table 创建表格
    table_data = [
        ["Connector", "Type", "Real-time", "Permissions"],
        ["Confluence", "Cloud", "Yes", "OAuth + API Token"],
        ["Google Drive", "Cloud", "Yes", "OAuth 2.0 Service Account"],
        ["SharePoint", "Cloud", "Yes", "Azure AD OAuth"],
        ["Slack", "Cloud", "No", "Bot Token"],
        ["GitHub", "Cloud", "Yes", "Personal Access Token"],
        ["Jira", "Cloud", "Yes", "API Token + Email"],
        ["Notion", "Cloud", "No", "Integration Token"],
        ["Salesforce", "Cloud", "Yes", "OAuth 2.0"],
    ]

    table = Table(table_data, colWidths=[120, 100, 80, 180])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
    ]))

    table.wrapOn(c, width, height)
    table.drawOn(c, 50, y - len(table_data) * 20)

    y -= len(table_data) * 20 + 40

    # 表格后的文本
    for line in [
        "",
        "Document Processing Pipeline:",
        "",
        "Stage 1 - Docfetching: Celery Beat checks connectors every 15s.",
        "Stage 2 - Extraction: Connector fetches documents in batches.",
        "Stage 3 - Processing: Documents are chunked, embedded, and indexed.",
        "Stage 4 - Indexing: Chunks are written to Vespa vector database.",
        "",
        "Chunking Strategy:",
        "- Sentence-based chunking with chonkie",
        "- Title prefix + content + metadata suffix",
        "- Mini-chunks for fine-grained retrieval",
        "- Large chunks for context-rich retrieval",
    ]:
        c.drawString(50, y, line)
        y -= 14

    c.showPage()
    c.save()
    packet2.seek(0)
    page2 = PdfReader(packet2).pages[0]
    writer.add_page(page2)

    # 写入文件
    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"Sample PDF created: {output_path}")


if __name__ == "__main__":
    create_sample_pdf("sample.pdf")
