# -*- coding: utf-8 -*-
"""
输出解析器引擎
支持多种解析方式：正则表达式、JSONPath、XPath、行提取、分隔符
"""
import re
import json
from typing import Dict, Any, List, Optional


class OutputParserEngine:
    """输出解析引擎"""
    
    @staticmethod
    def parse(output: str, parser_type: str, expression: str, default_value: str = "") -> str:
        """
        解析输出
        
        Args:
            output: 原始输出文本
            parser_type: 解析类型 (regex, jsonpath, xpath, line, split)
            expression: 解析表达式
            default_value: 默认值（解析失败时返回）
        
        Returns:
            解析结果字符串
        """
        try:
            if parser_type == "regex":
                return OutputParserEngine._parse_regex(output, expression, default_value)
            elif parser_type == "jsonpath":
                return OutputParserEngine._parse_jsonpath(output, expression, default_value)
            elif parser_type == "xpath":
                return OutputParserEngine._parse_xpath(output, expression, default_value)
            elif parser_type == "line":
                return OutputParserEngine._parse_line(output, expression, default_value)
            elif parser_type == "split":
                return OutputParserEngine._parse_split(output, expression, default_value)
            else:
                return default_value
        except Exception as e:
            print(f"解析失败 [{parser_type}]: {e}")
            return default_value
    
    @staticmethod
    def _parse_regex(output: str, expression: str, default_value: str) -> str:
        """正则表达式解析"""
        match = re.search(expression, output, re.MULTILINE | re.DOTALL)
        if match:
            # 如果有捕获组，返回第一个捕获组；否则返回整个匹配
            return match.group(1) if match.groups() else match.group(0)
        return default_value
    
    @staticmethod
    def _parse_jsonpath(output: str, expression: str, default_value: str) -> str:
        """JSONPath 解析（简化版本）"""
        try:
            # 尝试解析 JSON
            data = json.loads(output)
            
            # 简化的 JSONPath 实现，支持 $.key.subkey 格式
            path = expression.strip()
            if path.startswith('$.'):
                path = path[2:]
            elif path.startswith('$'):
                path = path[1:]
            
            # 按点分割路径
            keys = path.split('.')
            result = data
            
            for key in keys:
                if not key:
                    continue
                # 支持数组索引 key[0]
                array_match = re.match(r'(.+?)\[(\d+)\]', key)
                if array_match:
                    key_name = array_match.group(1)
                    index = int(array_match.group(2))
                    if key_name:
                        result = result[key_name]
                    result = result[index]
                else:
                    result = result[key]
            
            return str(result) if result is not None else default_value
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            return default_value
    
    @staticmethod
    def _parse_xpath(output: str, expression: str, default_value: str) -> str:
        """XPath 解析"""
        try:
            from xml.etree import ElementTree as ET
            
            # 尝试解析 XML
            root = ET.fromstring(output)
            
            # 使用 ElementTree 的 find/findall
            # 注意：ElementTree 的 XPath 支持有限
            elements = root.findall(expression)
            if elements:
                # 返回第一个匹配元素的文本
                if elements[0].text:
                    return elements[0].text
                # 如果没有文本，尝试返回元素的字符串表示
                return ET.tostring(elements[0], encoding='unicode')
            
            # 尝试直接 find
            element = root.find(expression)
            if element is not None:
                return element.text or ET.tostring(element, encoding='unicode')
            
            return default_value
        except ET.ParseError:
            return default_value
    
    @staticmethod
    def _parse_line(output: str, expression: str, default_value: str) -> str:
        """行提取解析"""
        lines = output.strip().split('\n')
        expr = expression.strip().lower()
        
        # line:N - 提取第 N 行（从 1 开始）
        if expr.startswith('line:'):
            try:
                line_num = int(expr[5:].strip())
                if 1 <= line_num <= len(lines):
                    return lines[line_num - 1].strip()
            except ValueError:
                pass
        
        # first - 第一行
        elif expr == 'first':
            return lines[0].strip() if lines else default_value
        
        # last - 最后一行
        elif expr == 'last':
            return lines[-1].strip() if lines else default_value
        
        # after:keyword - 关键字后的内容
        elif expr.startswith('after:'):
            keyword = expression[6:].strip()  # 保持原始大小写
            for line in lines:
                if keyword in line:
                    idx = line.index(keyword)
                    return line[idx + len(keyword):].strip()
        
        # before:keyword - 关键字前的内容
        elif expr.startswith('before:'):
            keyword = expression[7:].strip()
            for line in lines:
                if keyword in line:
                    idx = line.index(keyword)
                    return line[:idx].strip()
        
        # contains:keyword - 包含关键字的行
        elif expr.startswith('contains:'):
            keyword = expression[9:].strip()
            for line in lines:
                if keyword in line:
                    return line.strip()

        return default_value

    @staticmethod
    def _parse_split(output: str, expression: str, default_value: str) -> str:
        """分隔符解析"""
        # 格式: sep:,index:2 或 sep:|index:0
        try:
            parts = expression.split('index:')
            if len(parts) != 2:
                return default_value

            sep_part = parts[0].strip()
            index_part = parts[1].strip()

            # 解析分隔符
            if sep_part.startswith('sep:'):
                separator = sep_part[4:].strip()
            else:
                separator = sep_part.strip()

            # 如果分隔符为空，使用空格
            if not separator:
                separator = ' '

            # 解析索引
            index = int(index_part)

            # 分割并获取
            items = output.strip().split(separator)
            if 0 <= index < len(items):
                return items[index].strip()
            elif index < 0 and abs(index) <= len(items):
                return items[index].strip()

            return default_value
        except (ValueError, IndexError):
            return default_value

    @staticmethod
    def parse_all(output: str, parsers: list) -> Dict[str, str]:
        """
        使用多个解析器解析输出

        Args:
            output: 原始输出
            parsers: OutputParser 对象列表

        Returns:
            变量名到值的字典，键格式为 var_xxx
        """
        result = {}
        for parser in parsers:
            if not parser.enabled:
                continue
            value = OutputParserEngine.parse(
                output,
                parser.parser_type,
                parser.expression,
                parser.default_value
            )
            # 变量名格式: var_xxx
            var_key = f"var_{parser.var_name}" if not parser.var_name.startswith('var_') else parser.var_name
            result[var_key] = value
        return result

    @staticmethod
    def get_parser_types() -> List[Dict[str, str]]:
        """获取支持的解析器类型列表"""
        return [
            {"id": "regex", "name": "正则表达式", "hint": "例: status:\\s*(\\w+)"},
            {"id": "jsonpath", "name": "JSONPath", "hint": "例: $.data.result"},
            {"id": "xpath", "name": "XPath", "hint": "例: .//status 或 ./response/code"},
            {"id": "line", "name": "行提取", "hint": "例: line:1, first, last, after:keyword"},
            {"id": "split", "name": "分隔符", "hint": "例: sep:,index:2"},
        ]

