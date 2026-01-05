"""
ファイル読み込みユーティリティ

アップロードされたファイルの形式を自動判定し、適切な方法で読み込む。
Excel形式（.xlsx, .xls）とCSV形式に対応。

機能:
- ファイル形式の自動判定
- Excelファイルの読み込み（openpyxl/xlrd）
- CSVファイルの読み込み（エンコーディング自動判定）
"""
import io
from typing import Any, Dict, List, Optional, Tuple, Union

import chardet
import pandas as pd
from fastapi import UploadFile


# =============================================================================
# ファイル形式判定
# =============================================================================

def detect_file_type(filename: str) -> str:
    """
    ファイル名から形式を判定する

    Args:
        filename: ファイル名

    Returns:
        ファイル形式（"xlsx", "xls", "csv", "unknown"）
    """
    if not filename:
        return "unknown"

    lower_name = filename.lower()

    if lower_name.endswith(".xlsx"):
        return "xlsx"
    elif lower_name.endswith(".xls"):
        return "xls"
    elif lower_name.endswith(".csv"):
        return "csv"
    else:
        return "unknown"


# =============================================================================
# エンコーディング検出
# =============================================================================

def detect_encoding(content: bytes) -> str:
    """
    バイト列のエンコーディングを検出する

    日本語ファイルで一般的なエンコーディングを優先的に判定。

    Args:
        content: ファイル内容（バイト列）

    Returns:
        検出されたエンコーディング名
    """
    # chardetで検出
    result = chardet.detect(content)
    detected = result.get("encoding", "utf-8")
    confidence = result.get("confidence", 0)

    # 高信頼度ならそのまま使用
    if confidence > 0.8 and detected:
        # 日本語エンコーディングの正規化
        encoding_map = {
            "SHIFT_JIS": "cp932",
            "SHIFT-JIS": "cp932",
            "Shift_JIS": "cp932",
            "Windows-1252": "cp932",  # 誤検出対策
            "ISO-8859-1": "cp932",    # 誤検出対策
        }
        return encoding_map.get(detected, detected)

    # 低信頼度の場合は日本語エンコーディングを試行
    # UTF-8 → CP932 → EUC-JP の順で試す
    for encoding in ["utf-8", "cp932", "euc-jp", "utf-16"]:
        try:
            content.decode(encoding)
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue

    # フォールバック
    return detected or "utf-8"


# =============================================================================
# Excelファイル読み込み
# =============================================================================

def read_excel_file(
    content: bytes,
    file_type: str = "xlsx",
    sheet_name: Union[str, int] = 0,
    header: Optional[int] = 0,
    skiprows: Optional[int] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Excelファイルを読み込む

    Args:
        content: ファイル内容（バイト列）
        file_type: ファイル形式（"xlsx" または "xls"）
        sheet_name: 読み込むシート名またはインデックス
        header: ヘッダー行（None=ヘッダーなし）
        skiprows: スキップする行数

    Returns:
        Tuple[pd.DataFrame, List[str]]: (DataFrameと警告メッセージリスト)
    """
    warnings = []

    # エンジン選択
    if file_type == "xlsx":
        engine = "openpyxl"
    else:
        engine = "xlrd"

    try:
        df = pd.read_excel(
            io.BytesIO(content),
            sheet_name=sheet_name,
            header=header,
            skiprows=skiprows,
            engine=engine,
        )
        return df, warnings
    except Exception as e:
        raise ValueError(f"Excelファイルの読み込みに失敗しました: {str(e)}")


def read_excel_raw(
    content: bytes,
    file_type: str = "xlsx",
) -> Tuple[Any, List[str]]:
    """
    Excelファイルをopenpyxlのワークブックとして読み込む

    財務データや製造データなど、特定のセル位置からデータを読む場合に使用。

    Args:
        content: ファイル内容（バイト列）
        file_type: ファイル形式

    Returns:
        Tuple[Workbook, List[str]]: (ワークブックと警告メッセージリスト)
    """
    warnings = []

    if file_type == "xls":
        warnings.append(".xls形式は非推奨です。.xlsx形式の使用を推奨します。")
        # xlrdで読んでからopenpyxlに変換するのは複雑なので、
        # まずpandasで読んでからの処理を推奨
        raise ValueError(".xls形式はこのエンドポイントでサポートされていません。.xlsx形式をお使いください。")

    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), data_only=True)
        return wb, warnings
    except Exception as e:
        raise ValueError(f"Excelファイルの読み込みに失敗しました: {str(e)}")


# =============================================================================
# CSVファイル読み込み
# =============================================================================

def read_csv_file(
    content: bytes,
    encoding: Optional[str] = None,
    header: Optional[int] = 0,
    skiprows: Optional[int] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    CSVファイルを読み込む（エンコーディング自動判定）

    Args:
        content: ファイル内容（バイト列）
        encoding: エンコーディング（指定しない場合は自動判定）
        header: ヘッダー行（None=ヘッダーなし）
        skiprows: スキップする行数

    Returns:
        Tuple[pd.DataFrame, List[str]]: (DataFrameと警告メッセージリスト)
    """
    warnings = []

    # エンコーディング自動判定
    if encoding is None:
        encoding = detect_encoding(content)
        warnings.append(f"エンコーディング '{encoding}' を自動検出しました")

    # CSVを読み込み
    try:
        text = content.decode(encoding)
        df = pd.read_csv(
            io.StringIO(text),
            header=header,
            skiprows=skiprows,
        )
        return df, warnings
    except UnicodeDecodeError as e:
        # 自動検出が失敗した場合、別のエンコーディングを試行
        for fallback_encoding in ["utf-8", "cp932", "euc-jp", "utf-16"]:
            if fallback_encoding != encoding:
                try:
                    text = content.decode(fallback_encoding)
                    df = pd.read_csv(io.StringIO(text), header=header, skiprows=skiprows)
                    warnings.append(f"フォールバックエンコーディング '{fallback_encoding}' を使用しました")
                    return df, warnings
                except (UnicodeDecodeError, Exception):
                    continue
        raise ValueError(f"ファイルのエンコーディングエラー: {str(e)}")
    except Exception as e:
        raise ValueError(f"CSVファイルの読み込みに失敗しました: {str(e)}")


def read_csv_raw(
    content: bytes,
    encoding: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """
    CSVファイルをテキストとして読み込む

    既存のパーサー関数と互換性を保つため、デコードされたテキストを返す。

    Args:
        content: ファイル内容（バイト列）
        encoding: エンコーディング（指定しない場合は自動判定）

    Returns:
        Tuple[str, List[str]]: (デコードされたテキストと警告メッセージリスト)
    """
    warnings = []

    # エンコーディング自動判定
    if encoding is None:
        encoding = detect_encoding(content)

    # デコード
    try:
        text = content.decode(encoding)
        return text, warnings
    except UnicodeDecodeError:
        # フォールバック
        for fallback_encoding in ["utf-8", "cp932", "euc-jp", "utf-16"]:
            if fallback_encoding != encoding:
                try:
                    text = content.decode(fallback_encoding)
                    warnings.append(f"フォールバックエンコーディング '{fallback_encoding}' を使用しました")
                    return text, warnings
                except UnicodeDecodeError:
                    continue
        raise ValueError(f"ファイルのエンコーディングを判定できません")


# =============================================================================
# 統合読み込み関数
# =============================================================================

def read_upload_file(
    content: bytes,
    filename: str,
    as_dataframe: bool = True,
    header: Optional[int] = 0,
    skiprows: Optional[int] = None,
) -> Tuple[Union[pd.DataFrame, str, Any], str, List[str]]:
    """
    アップロードファイルを適切な方法で読み込む

    ファイル形式を自動判定し、Excel/CSVを適切に処理する。

    Args:
        content: ファイル内容（バイト列）
        filename: ファイル名
        as_dataframe: DataFrameとして読み込むか（Falseの場合は生データ）
        header: ヘッダー行
        skiprows: スキップする行数

    Returns:
        Tuple[Union[pd.DataFrame, str, Any], str, List[str]]:
            (データ, ファイル形式, 警告メッセージリスト)
    """
    file_type = detect_file_type(filename)
    warnings = []

    if file_type == "xlsx" or file_type == "xls":
        if as_dataframe:
            data, w = read_excel_file(
                content, file_type, header=header, skiprows=skiprows
            )
        else:
            data, w = read_excel_raw(content, file_type)
        warnings.extend(w)
        return data, file_type, warnings

    elif file_type == "csv":
        if as_dataframe:
            data, w = read_csv_file(content, header=header, skiprows=skiprows)
        else:
            data, w = read_csv_raw(content)
        warnings.extend(w)
        return data, file_type, warnings

    else:
        raise ValueError(
            f"サポートされていないファイル形式です: {filename}"
            "（.xlsx, .xls, .csv のいずれかを使用してください）"
        )


async def read_upload_file_async(
    file: UploadFile,
    as_dataframe: bool = True,
    header: Optional[int] = 0,
    skiprows: Optional[int] = None,
) -> Tuple[Union[pd.DataFrame, str, Any], str, List[str]]:
    """
    UploadFileから直接読み込む（非同期版）

    Args:
        file: FastAPIのUploadFileオブジェクト
        as_dataframe: DataFrameとして読み込むか
        header: ヘッダー行
        skiprows: スキップする行数

    Returns:
        Tuple[Union[pd.DataFrame, str, Any], str, List[str]]:
            (データ, ファイル形式, 警告メッセージリスト)
    """
    content = await file.read()
    return read_upload_file(
        content,
        file.filename or "",
        as_dataframe=as_dataframe,
        header=header,
        skiprows=skiprows,
    )
