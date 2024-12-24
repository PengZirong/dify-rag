# -*- encoding: utf-8 -*-
# File: pdf_extractor.py
# Description: None

from collections import Counter
from typing import Optional

import pymupdf

from dify_rag.extractor.extractor_base import BaseExtractor
from dify_rag.extractor.utils import fix_error_pdf_content, is_gibberish
from dify_rag.models.document import Document


class PdfExtractor(BaseExtractor):
    def __init__(self, file_path: str, file_cache_key: Optional[str] = None) -> None:
        self._file_path = file_path
        self._file_cache_key = file_cache_key

    @staticmethod
    def remove_invalid_char(text_blocks):
        block_content = ""
        for block in text_blocks:
            block_text = block[4]
            if is_gibberish(block_text):
                block_content += block_text
        return fix_error_pdf_content(block_content)

    @staticmethod
    def _collect_page_metrics(page):
        """收集单页的页眉页脚度量数据"""
        text_blocks = page.get_text("blocks")
        if not text_blocks:
            return None
        
        header_y, footer_y = float('inf'), float('-inf')
        header_idx, footer_idx = -1, -1
        header_height, footer_height = 0, 0

        for idx, block in enumerate(text_blocks):
            _, y0, _, y1, *_ = block
            if y0 < header_y:
                header_y, header_idx, header_height = y0, idx, y1 - y0
            if y1 > footer_y:
                footer_y, footer_idx, footer_height = y1, idx, y1 - y0

        return {
            'text_blocks': text_blocks,
            'header_idx': header_idx,
            'footer_idx': footer_idx,
            'header_height': header_height,
            'footer_height': footer_height
        }

    @staticmethod
    def _should_remove_headers_footers(page_metrics, threshold=0.9):
        """判断是否应该移除页眉页脚"""
        if not page_metrics:
            return False, False

        header_heights = [m['header_height'] for m in page_metrics if m]
        footer_heights = [m['footer_height'] for m in page_metrics if m]

        def exists_common_height(heights):
            if not heights:
                return False
            _, count = Counter(heights).most_common(1)[0]
            return count / len(heights) >= threshold
            
        return exists_common_height(header_heights), exists_common_height(footer_heights)

    @staticmethod
    def filter_doc_header_or_footer(doc):
        """
        过滤文档中的页眉页脚
        页眉和页脚，每页都应该具备且格式相同
        """
        page_metrics = [PdfExtractor._collect_page_metrics(page) for page in doc]

        header_exists, footer_exists = PdfExtractor._should_remove_headers_footers(page_metrics)

        if not header_exists and not footer_exists:
            return [m['text_blocks'] for m in page_metrics if m]

        filtered_page_blocks = []
        for metrics in page_metrics:
            if not metrics:
                continue

            indices_to_remove = set()
            if header_exists and metrics['header_idx'] != -1:
                indices_to_remove.add(metrics['header_idx'])
            if footer_exists and metrics['footer_idx'] != -1:
                indices_to_remove.add(metrics['footer_idx'])

            filtered_blocks = [
                block for idx, block in enumerate(metrics['text_blocks'])
                if idx not in indices_to_remove
            ]
            filtered_page_blocks.append(filtered_blocks)

        return filtered_page_blocks

    @staticmethod
    def split_completion(content, current_split):
        split_content_list = content.split(current_split)
        if len(split_content_list) > 1:
            return split_content_list[0], "".join(split_content_list[1:])
        return "", split_content_list.pop()

    def extract(self) -> list[Document]:
        # 基于pymupdf版本
        doc = pymupdf.open(self._file_path)
        toc = doc.get_toc()
        content, documents = "", []
        filtered_page_blocks = self.filter_doc_header_or_footer(doc)
        for text_blocks in filtered_page_blocks:
            content += self.remove_invalid_char(text_blocks)
        if toc:
            prxfix_split = ""
            for _toc in toc:
                current_split = _toc[1]
                prefix, suffix = self.split_completion(content, current_split)
                documents.append(Document(page_content=prxfix_split + prefix))
                prxfix_split, content = current_split, suffix
            documents.append(Document(page_content=prxfix_split + content))
        else:
            documents.append(Document(page_content=content))
        return documents
