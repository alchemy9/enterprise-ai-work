"""Text extraction with source anchors; uploaded files are never executed."""
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from .domain import BusinessError, require


def extract_document(filename, raw):
    suffix=Path(filename).suffix.lower()
    require(suffix in {'.txt','.md','.docx','.pdf'},'支持 TXT、Markdown、DOCX、PDF 文本文件')
    require(0<len(raw)<=50*1024*1024,'文件必须非空且不超过 50 MB')
    pages=[]
    if suffix in {'.txt','.md'}:
        try:
            value=raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:
                value=raw.decode('gb18030')
            except UnicodeDecodeError:
                raise BusinessError(400,'PARSE_FAILED','文件不是可识别的 UTF-8/GB18030 文本')
        require('\x00' not in value,'文件包含二进制内容，无法作为文本解析')
        pages=[{'anchor':'全文','text':value}]
    elif suffix=='.docx':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                require(sum(x.file_size for x in z.infolist())<100*1024*1024,'DOCX 解压内容超过限制')
                require('word/document.xml' in z.namelist(),'不是有效的 DOCX 文件')
                xml=z.read('word/document.xml')
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            root=ET.fromstring(xml)
            body=root.find('w:body',ns);require(body is not None,'DOCX 没有可解析正文')
            paragraph_number=0;table_number=0
            for element in body:
                if element.tag=='{'+ns['w']+'}p':
                    paragraph_number+=1;value=''.join(t.text or '' for t in element.findall('.//w:t',ns))
                    style=element.find('w:pPr/w:pStyle',ns)
                    if style is not None:
                        match=re.search(r'(?:Heading|标题)\s*([1-6])',style.get('{'+ns['w']+'}val',''),re.I)
                        if match:value='#'*int(match[1])+' '+value
                    if value.strip():pages.append({'anchor':f'段落 {paragraph_number}','text':value})
                elif element.tag=='{'+ns['w']+'}tbl':
                    table_number+=1;records=[];merged=False
                    for tr in element.findall('w:tr',ns):
                        cells=[]
                        for tc in tr.findall('w:tc',ns):
                            cells.append(' / '.join(''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in tc.findall('.//w:p',ns)).strip())
                            merged=merged or tc.find('w:tcPr/w:gridSpan',ns) is not None or tc.find('w:tcPr/w:vMerge',ns) is not None
                        records.append(cells)
                    if not records:continue
                    headers=records[0];quality='低质量：存在合并单元格，行列对应与单位需人工核对，不能作为唯一计算依据。' if merged or any(len(r)!=len(headers) for r in records) else '保留首行表头；单位以原文为准，不推测缺失单位。'
                    for i,record in enumerate(records[1:] or records,2):
                        values='；'.join((headers[j] if j<len(headers) and headers[j] else f'列 {j+1}')+'：'+value for j,value in enumerate(record))
                        if values.strip():pages.append({'anchor':f'表格 {table_number} · 第 {i} 行','text':f'[表格 {table_number}；{quality}]\n表头：'+ ' | '.join(headers)+'\n'+values,'quality':'LOW' if merged else 'TEXT'})
        except (zipfile.BadZipFile,ET.ParseError,KeyError):
            raise BusinessError(400,'PARSE_FAILED','DOCX 损坏或加密，无法解析')
    else:
        require(raw.startswith(b'%PDF-'),'不是有效的 PDF 文件')
        try:
            from pypdf import PdfReader
        except ImportError:
            raise BusinessError(503,'DEPENDENCY_MISSING','PDF 解析依赖未安装，请使用项目 .venv 启动或安装 requirements.txt')
        try:
            reader=PdfReader(io.BytesIO(raw))
            require(not reader.is_encrypted,'加密 PDF 暂不支持，请先提供解密后的文本 PDF','PDF_ENCRYPTED')
            require(len(reader.pages)<=1000,'PDF 超过 1000 页，请拆分后上传')
            pages=[{'anchor':f'第 {i+1} 页','text':page.extract_text() or ''} for i,page in enumerate(reader.pages)]
        except BusinessError:
            raise
        except Exception:
            raise BusinessError(400,'PARSE_FAILED','PDF 文本解析失败，请检查文件是否损坏')
    content='\n\n'.join(p['text'] for p in pages).strip()
    require(bool(content),'未提取到文本，扫描件需先 OCR；本次未建立空索引','NO_TEXT')
    require(len(content)<=3_000_000,'提取文本过长，请拆分文件')
    return content,pages


def make_chunks(pages):
    """Keep paragraph/page locations and bounded overlap; parent uses the same ACL."""
    chunks=[]
    heading='正文'
    for page in pages:
        blocks=re.split(r'\n\s*\n|(?<=。)\n',page['text'])
        for number,block in enumerate(blocks,1):
            block=block.strip()
            if not block:
                continue
            if block.startswith('#'):
                first=block.splitlines()[0]
                heading=first.lstrip('# ').strip()[:120]
            for start in range(0,len(block),700):
                part=block[max(0,start-80):start+780]
                chunks.append({'anchor':f"{page['anchor']} · 片段 {number}",'heading':heading,'content':part,'parent_content':block[:4000],'parent_truncated':len(block)>4000})
    return chunks
