"""Portable DOCX export of authorized report text (no external document service)."""
import io
import re
import zipfile
from xml.sax.saxutils import escape
from .db import now
from .domain import local_date


def report_markdown(report,user):
    d=report['current']['data'];m=d['metrics'];formal=report['status'] in {'PUBLISHED','SUPERSEDED'}
    lines=[f"# {d['title']}",f"项目：{report['project_name']}",f"状态：{report['status']} / v{report['current_version']}" if formal else f"未经审核正式发布 · {report['status']} / v{report['current_version']}",f"导出人：{user['name']}；导出时间：{now()}",'模式：本地规则与资料摘录，未调用真实 LLM。','## 一、报告概况与数据截点',f"周期：{d['period_start']} 至 {d['period_end']}",f"数据截点：{d['cutoff_time']}",f"冻结快照：{d['snapshot_id']}"]
    if d.get('data_source'):lines.append('来源：'+d['data_source']['name']+' / '+d['data_source']['mode']+' / '+d['data_source'].get('note',''))
    lines+=['## 二、关键统计与口径',f"非取消任务：{m['total']}；已完成：{m['completed']}；完成率："+(str(m['completion_rate'])+'%' if m['completion_rate'] is not None else '不适用'),f"本期完成：{m['period_completed']}；未完成逾期：{m['overdue_count']}；完成时逾期：{m['completed_late']}",'口径：数字由冻结台账计算；截止日早于截点本地日期且未完成判逾期，当天到期不逾期；缺完成时间不计本期完成数。']
    comparison=m.get('comparison')
    if comparison:lines.append(f"上期比较：{comparison['period_end']}，来源 {comparison['kind']} / {comparison['snapshot_id']}；完成率变化 {comparison['completion_rate_change']} 个百分点；未完成逾期变化 {comparison['overdue_change']} 项。")
    lines+=['## 三、本期完成与主要进展']
    if d.get('human_adjustments'):
        lines+=['人工调整（单独声明，不改变冻结台账或规则计算）：']+[f"- {a['metric']}：规则 {a['source_value']} → 人工 {a['value']}；原因：{a['reason']}；操作者 {a['actor_id']}；{a['at']}" for a in d['human_adjustments']]
    completed=d.get('completed_tasks')
    if completed is None:completed=[e['row'] for e in d['evidence'] if e.get('row',{}).get('status')=='DONE' and e['row'].get('completed_at') and d['period_start']<=local_date(e['row']['completed_at']).isoformat()<=min(d['period_end'],d['cutoff_time'][:10])]
    lines+=[f"- {x['task_id']}：{x['title']}；完成 {x['completed_at']}" for x in completed] or ['该版本未保存本期完成明细，统计见上节。']
    lines+=['## 四、进行中、逾期与里程碑']
    lines+=[f"- {x['task_id']}：{x['title']}；状态 {x['status']}；截止 {x.get('due_date') or '未提供'}" for x in d.get('in_progress_tasks',[])]
    lines+=[f"- 里程碑 {x['name']}：计划 {x['due_date']}，{x['completed']}/{x['total']}，状态 {x['status']}，{'关键' if x['critical'] else '普通'}" for x in m.get('milestones',[])]
    lines+=['## 五、风险与问题']
    for r in d['risks']:lines += [f"- {r['title']} / {r['level']}：{r['fact']}",f"  规则：{r.get('rule_trigger','台账逾期')}；可能原因：{r['hypothesis']}；影响：{r.get('impact','待核实')}；引用：{', '.join(r['evidence_ids'])}"]
    lines+=['## 六、建议整改清单']+[f"- {r['recommendation']}；负责人、日期与验收标准需另行确认。" for r in d['risks']]
    lines+=['## 七、下周期关注与人工补充',d['narrative']]
    if d.get('focus'):lines.append('发起人关注：'+d['focus'])
    lines+=['## 八、数据缺口与引用清单']+['- '+x for x in d['missing']]
    for e in d['evidence']:
        label='文档' if e.get('kind')=='DOCUMENT' else '里程碑计划' if e.get('kind')=='MILESTONE' else '台账'
        lines.append(f"- {e['evidence_id']}：{label} {e['title']} / {e['locator']} / {e['version']}")
    return '\n\n'.join(lines)


def report_pdf(markdown):
    """Embed a Unicode TrueType font; no viewer-side CJK language pack needed."""
    import os
    from pathlib import Path
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from .domain import BusinessError
    name='EAWUnicode'
    if name not in pdfmetrics.getRegisteredFontNames():
        candidates=[os.environ.get('EAW_PDF_FONT',''),'/Library/Fonts/Arial Unicode.ttf','C:/Windows/Fonts/simhei.ttf','/usr/share/fonts/truetype/wqy/wqy-microhei.ttc','/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf']
        font=next((str(Path(p)) for p in candidates if p and Path(p).is_file()),None)
        if not font:raise BusinessError(503,'PDF_FONT_MISSING','未找到可嵌入的中文字体，请用 EAW_PDF_FONT 指定本机中文 TrueType 字体后重试')
        pdfmetrics.registerFont(TTFont(name,font))
    output=io.BytesIO();pdf=canvas.Canvas(output,pagesize=(595.28,841.89),pageCompression=1)
    pdf.setTitle(markdown.splitlines()[0].lstrip('# ')[:120]);pdf.setAuthor('Enterprise AI Work')
    y=789;page=1
    def footer():
        pdf.setFont(name,8);pdf.setFillColorRGB(.4,.45,.52);pdf.drawString(46,30,'Enterprise AI Work · 本地演示报告');pdf.drawRightString(549,30,str(page))
    for raw in markdown.splitlines():
        if not raw.strip():y-=7;continue
        heading=raw.startswith('#');size=17 if raw.startswith('# ') else 12 if heading else 10
        value=re.sub(r'^[#]+\s*','',raw) if heading else raw
        value=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',value)
        line=''
        for char in value+'\n':
            if char=='\n' or pdfmetrics.stringWidth(line+char,name,size)>503:
                if y<53:footer();pdf.showPage();page+=1;y=789
                pdf.setFont(name,size);pdf.setFillColorRGB(.12,.2,.32) if heading else pdf.setFillColorRGB(.16,.2,.25)
                pdf.drawString(46,y,line);y-=size*1.65;line=''
            if char!='\n':line+=char
    footer();pdf.save();return output.getvalue()


def report_docx(markdown):
    markdown=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',markdown)
    paragraphs=[]
    for line in markdown.splitlines():
        style='Title' if line.startswith('# ') else 'Heading1' if line.startswith('## ') else 'Normal'
        value=line.lstrip('# ').strip() if line.startswith('#') else line
        paragraphs.append(f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t xml:space="preserve">{escape(value)}</w:t></w:r></w:p>')
    document='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+''.join(paragraphs)+'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>'
    styles='''<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Aptos" w:eastAsia="Microsoft YaHei"/><w:sz w:val="22"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="320" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="Heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="280" w:after="140"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style></w:styles>'''
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/_rels/document.xml.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('word/document.xml',document)
        z.writestr('word/styles.xml',styles)
    return output.getvalue()
