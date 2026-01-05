"""
CSVアップロードエンドポイントモジュール

CSVファイルのアップロードと処理を行うエンドポイントを提供する。
店舗別CSV、商品別CSVの2種類をサポート。
財務データExcel、製造データExcelのアップロードもサポート。

エンドポイント:
- POST /upload/store-kpi: 店舗別売上CSVのアップロード
- POST /upload/product-kpi: 商品別売上CSVのアップロード
- GET /upload/template/{csv_type}: CSVテンプレートのダウンロード
- POST /upload/financial: 財務データExcelのアップロード
- POST /upload/manufacturing: 製造データExcelのアップロード
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from supabase import Client
from io import StringIO

from app.api.deps import get_current_user, get_supabase_admin
from app.schemas.kpi import User
from app.schemas.upload import (
    StoreKPIUploadResult,
    ProductKPIUploadResult,
    UploadErrorDetail,
    ValidationError,
)
from app.schemas.financial import (
    FinancialUploadResult,
    FinancialParseError,
    ManufacturingUploadResult,
    ManufacturingSummary,
)
from app.services.parser import (
    parse_store_csv,
    parse_product_csv,
    validate_store_data,
    validate_product_data,
)
from app.services.import_service import (
    import_store_kpi,
    import_product_kpi,
    get_segments_for_department,
)
from app.services.excel_parser import (
    parse_financial_excel,
    parse_manufacturing_excel,
    get_financial_sample,
    get_manufacturing_sample,
)
from app.services.financial_import_service import (
    import_financial_data,
    import_manufacturing_data,
)


# ルーター作成
router = APIRouter(tags=["アップロード"])


# =============================================================================
# 店舗別CSVアップロード
# =============================================================================

@router.post(
    "/store-kpi",
    response_model=StoreKPIUploadResult,
    summary="店舗別売上CSVをアップロード",
    description="""
    店舗別売上CSVファイルをアップロードして処理する。

    ## CSVフォーマット
    - 1行目: 期間情報（例: 期間,2025年4月1日～2025年4月30日）
    - 2行目: ヘッダー（店舗CD,店舗名称,今年度(税込小計),今年度(客数),...)
    - 3行目以降: データ

    ## 処理内容
    1. ファイル読み込み・エンコーディング自動判定
    2. CSVパース・バリデーション
    3. 店舗マスタとの照合
    4. kpi_valuesテーブルへのインポート（売上高、客数）

    ## 対応エンコーディング
    UTF-8, Shift-JIS, CP932（Windows日本語）
    """,
    responses={
        200: {
            "description": "インポート成功",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "period": "2025-04-01",
                        "imported_count": 34,
                        "errors": [],
                        "warnings": ["店舗CD 99 はマスタに存在しません"]
                    }
                }
            }
        },
        400: {
            "description": "ファイル形式エラー",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "CSVファイルの形式が正しくありません。期間行が見つかりません。"
                    }
                }
            }
        },
        422: {
            "description": "バリデーションエラー",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "success": False,
                            "message": "データにエラーがあります",
                            "errors": [
                                {"row": 3, "column": "今年度(税込小計)", "message": "数値ではありません", "value": "abc"}
                            ]
                        }
                    }
                }
            }
        }
    }
)
async def upload_store_kpi(
    file: UploadFile = File(..., description="アップロードする店舗別売上CSV"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> StoreKPIUploadResult:
    """
    店舗別売上CSVをアップロードして処理する

    Args:
        file: アップロードされたCSVファイル
        current_user: 認証されたユーザー
        supabase: Supabase管理者クライアント

    Returns:
        StoreKPIUploadResult: インポート結果
    """
    # ファイル読み込み
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ファイルの読み込みに失敗しました: {str(e)}"
        )

    # CSVパース（Excelファイルにも対応）
    parsed = parse_store_csv(content, file.filename or "")

    if not parsed["success"]:
        # パースエラー
        if parsed["errors"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=parsed["errors"][0]
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSVファイルのパースに失敗しました"
        )

    # 部門IDを取得（ユーザーの所属部門、または店舗部門をデフォルト）
    department_id = current_user.department_id
    if not department_id:
        # 店舗部門をデフォルトとして取得
        try:
            dept_response = supabase.table("departments").select("id").eq(
                "slug", "store"
            ).single().execute()
            department_id = dept_response.data["id"]
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="部門の取得に失敗しました"
            )

    # 店舗マスタ取得とバリデーション
    try:
        segments = await get_segments_for_department(supabase, department_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"店舗マスタの取得に失敗しました: {str(e)}"
        )

    valid_data, validation_warnings = validate_store_data(parsed["data"], segments)
    parsed["data"] = valid_data
    parsed["warnings"].extend(validation_warnings)

    # インポート実行
    try:
        import_result = await import_store_kpi(supabase, parsed, department_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"データのインポートに失敗しました: {str(e)}"
        )

    # 結果をまとめる
    all_errors = parsed["errors"] + import_result.get("errors", [])
    all_warnings = parsed["warnings"] + import_result.get("warnings", [])

    return StoreKPIUploadResult(
        success=len(all_errors) == 0,
        period=parsed["period"],
        imported_count=import_result.get("imported", 0),
        errors=all_errors,
        warnings=all_warnings,
    )


# =============================================================================
# 商品別CSVアップロード
# =============================================================================

@router.post(
    "/product-kpi",
    response_model=ProductKPIUploadResult,
    summary="商品別売上CSVをアップロード",
    description="""
    商品別売上CSVファイルをアップロードして処理する。

    ## CSVフォーマット
    - 1行目: 期間情報（例: 期間,2025年4月1日～2025年4月30日）
    - 2行目: ヘッダー（商品CD,商品名,大分類名,中分類名,小分類名,件数,税込小計,...)
    - 3行目以降: データ

    ## 処理内容
    1. ファイル読み込み・エンコーディング自動判定
    2. CSVパース・バリデーション
    3. 商品マッピング処理（未登録商品は自動登録）
    4. KPIグループ別に集計
    5. kpi_valuesテーブルへのインポート

    ## 商品マッピング
    - 大分類名からKPIグループ（ぎょうざ、しょうが入ぎょうざ、付属品など）を自動判定
    - 未知のカテゴリはproduct_mappingsにkpi_id=NULLで登録
    """,
    responses={
        200: {
            "description": "インポート成功",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "period": "2025-04-01",
                        "imported_count": 5,
                        "new_products": ["新商品X"],
                        "unmapped_products": [],
                        "errors": [],
                        "warnings": []
                    }
                }
            }
        }
    }
)
async def upload_product_kpi(
    file: UploadFile = File(..., description="アップロードする商品別売上CSV"),
    segment_id: str = Query(None, description="対象セグメントID（指定しない場合は本社）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> ProductKPIUploadResult:
    """
    商品別売上CSVをアップロードして処理する

    Args:
        file: アップロードされたCSVファイル
        segment_id: 対象セグメントID（オプション）
        current_user: 認証されたユーザー
        supabase: Supabase管理者クライアント

    Returns:
        ProductKPIUploadResult: インポート結果
    """
    # ファイル読み込み
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ファイルの読み込みに失敗しました: {str(e)}"
        )

    # CSVパース（Excelファイルにも対応）
    parsed = parse_product_csv(content, file.filename or "")

    if not parsed["success"]:
        if parsed["errors"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=parsed["errors"][0]
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSVファイルのパースに失敗しました"
        )

    # 部門IDを取得
    department_id = current_user.department_id
    if not department_id:
        try:
            dept_response = supabase.table("departments").select("id").eq(
                "slug", "store"
            ).single().execute()
            department_id = dept_response.data["id"]
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="部門の取得に失敗しました"
            )

    # データバリデーション
    valid_data, validation_warnings = validate_product_data(parsed["data"])
    parsed["data"] = valid_data
    parsed["warnings"].extend(validation_warnings)

    # インポート実行
    try:
        import_result = await import_product_kpi(
            supabase, parsed, department_id, segment_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"データのインポートに失敗しました: {str(e)}"
        )

    # 結果をまとめる
    all_errors = parsed["errors"] + import_result.get("errors", [])
    all_warnings = parsed["warnings"] + import_result.get("warnings", [])

    return ProductKPIUploadResult(
        success=len(all_errors) == 0,
        period=parsed["period"],
        imported_count=import_result.get("imported", 0),
        new_products=import_result.get("new_products", []),
        unmapped_products=import_result.get("unmapped", []),
        stores_processed=import_result.get("stores_processed", []),
        errors=all_errors,
        warnings=all_warnings,
    )


# =============================================================================
# CSVテンプレートダウンロード
# =============================================================================

@router.get(
    "/template/{csv_type}",
    summary="CSVテンプレートをダウンロード",
    description="""
    CSVアップロード用のテンプレートファイルをダウンロードする。

    ## csv_type
    - `store`: 店舗別売上CSV
    - `product`: 商品別売上CSV
    """,
    responses={
        200: {
            "description": "CSVテンプレート",
            "content": {
                "text/csv": {}
            }
        },
        400: {
            "description": "無効なCSVタイプ"
        }
    }
)
async def download_template(
    csv_type: str,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    CSVテンプレートをダウンロードする

    Args:
        csv_type: CSVタイプ（"store" または "product"）
        current_user: 認証されたユーザー

    Returns:
        StreamingResponse: CSVファイル
    """
    if csv_type == "store":
        # 店舗別CSVテンプレート
        content = """期間,2025年4月1日～2025年4月30日
店舗CD,店舗名称,今年度(税込小計),今年度(税抜小計),今年度(客数),前年度(税込小計),前年度(客数)
2,隼人店,0,0,0,0,0
3,鷹尾店,0,0,0,0,0
4,中町店,0,0,0,0,0
5,三股店,0,0,0,0,0
"""
        filename = "store_kpi_template.csv"

    elif csv_type == "product":
        # 商品別CSVテンプレート
        content = """期間,2025年4月1日～2025年4月30日
商品CD,商品名,大分類名,中分類名,小分類名,件数,税込小計,税抜小計
001,ぎょうざ２０個,ぎょうざ,生ぎょうざ,20個入,0,0,0
002,ぎょうざ３０個,ぎょうざ,生ぎょうざ,30個入,0,0,0
010,タレ小,たれ・スープ,たれ,小,0,0,0
"""
        filename = "product_kpi_template.csv"

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無効なCSVタイプです: {csv_type}（'store' または 'product' を指定してください）"
        )

    # CSVをUTF-8 with BOMで出力（Excelで開くため）
    output = StringIO()
    output.write('\ufeff')  # BOM
    output.write(content)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue().encode('utf-8')]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


# =============================================================================
# テスト用エンドポイント（開発環境のみ）
# =============================================================================

@router.post(
    "/test/parse-store",
    summary="[テスト] 店舗CSVパース確認",
    description="認証なしでCSVパース処理のみをテストする（開発環境用）",
    tags=["テスト"],
)
async def test_parse_store_csv(
    file: UploadFile = File(..., description="テストする店舗別CSV"),
):
    """
    店舗CSVのパース処理をテストする（認証なし）
    """
    content = await file.read()
    parsed = parse_store_csv(content, file.filename or "")
    return {
        "success": parsed["success"],
        "period": str(parsed["period"]) if parsed["period"] else None,
        "row_count": len(parsed["data"]),
        "data_preview": parsed["data"][:3] if parsed["data"] else [],
        "errors": parsed["errors"],
        "warnings": parsed["warnings"],
    }


@router.post(
    "/test/parse-product",
    summary="[テスト] 商品CSVパース確認",
    description="認証なしでCSVパース処理のみをテストする（開発環境用）",
    tags=["テスト"],
)
async def test_parse_product_csv(
    file: UploadFile = File(..., description="テストする商品別CSV"),
):
    """
    商品CSVのパース処理をテストする（認証なし）
    """
    content = await file.read()
    parsed = parse_product_csv(content, file.filename or "")

    # 店舗別統計を集計
    stores = {}
    categories = {}
    for row in parsed["data"]:
        store_key = (row.get("store_code", ""), row.get("store_name", ""))
        if store_key not in stores:
            stores[store_key] = {"count": 0, "total_sales": 0}
        stores[store_key]["count"] += 1
        stores[store_key]["total_sales"] += row.get("sales", 0)

        cat = row.get("category", "不明")
        categories[cat] = categories.get(cat, 0) + 1

    store_stats = [
        {
            "store_code": k[0],
            "store_name": k[1],
            "product_count": v["count"],
            "total_sales": v["total_sales"],
        }
        for k, v in sorted(stores.items(), key=lambda x: x[0][0])
    ]

    return {
        "success": parsed["success"],
        "period": str(parsed["period"]) if parsed["period"] else None,
        "row_count": len(parsed["data"]),
        "store_count": len(stores),
        "store_stats": store_stats,
        "categories": categories,
        "data_preview": parsed["data"][:5] if parsed["data"] else [],
        "errors": parsed["errors"],
        "warnings": parsed["warnings"],
    }


# =============================================================================
# アップロード履歴（将来の拡張用）
# =============================================================================

@router.get(
    "/history",
    summary="アップロード履歴を取得",
    description="過去のCSVアップロード履歴を取得する（将来の拡張用）",
)
async def get_upload_history(
    current_user: User = Depends(get_current_user),
):
    """
    アップロード履歴を取得する

    将来の拡張用。現在は空のリストを返す。
    """
    # TODO: アップロード履歴テーブルを作成して実装
    return {
        "uploads": [],
        "message": "この機能は将来の拡張用です"
    }


# =============================================================================
# 財務データExcelアップロード
# =============================================================================

@router.post(
    "/financial",
    response_model=FinancialUploadResult,
    summary="財務データExcelをアップロード",
    description="""
    財務データExcelファイルをアップロードして処理する。

    ## Excelフォーマット
    - B1: 対象年月（日付）
    - B2: データ区分（"実績" または "予算"）
    - 4行目以降: 財務項目データ

    ## 処理内容
    1. Excelファイル読み込み
    2. パース・バリデーション
    3. financial_dataテーブルへのUpsert

    ## 対応形式
    .xlsx形式のみ対応
    """,
    responses={
        200: {
            "description": "インポート成功",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "財務データをインポートしました",
                        "month": "2025-11-01",
                        "data_type": "実績",
                        "action": "updated",
                        "warnings": []
                    }
                }
            }
        },
        400: {
            "description": "ファイル形式エラー"
        },
        422: {
            "description": "バリデーションエラー"
        }
    }
)
async def upload_financial_excel(
    file: UploadFile = File(..., description="アップロードする財務データExcel（.xlsx）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> FinancialUploadResult:
    """
    財務データExcelをアップロードして処理する

    Args:
        file: アップロードされたExcelファイル
        current_user: 認証されたユーザー
        supabase: Supabase管理者クライアント

    Returns:
        FinancialUploadResult: インポート結果
    """
    # ファイル形式チェック
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Excelファイル（.xlsx形式）をアップロードしてください"
        )

    # ファイル読み込み
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ファイルの読み込みに失敗しました: {str(e)}"
        )

    # Excelパース
    parsed = parse_financial_excel(content)

    if not parsed["success"]:
        # パースエラー
        if parsed["errors"]:
            errors = [
                FinancialParseError(**e) if isinstance(e, dict) else FinancialParseError(message=str(e))
                for e in parsed["errors"]
            ]
            return FinancialUploadResult(
                success=False,
                message="データにエラーがあります",
                errors=errors,
                warnings=parsed.get("warnings", []),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Excelファイルのパースに失敗しました"
        )

    # DBインポート
    try:
        import_result = await import_financial_data(supabase, parsed)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"データのインポートに失敗しました: {str(e)}"
        )

    if not import_result["success"]:
        errors = [
            FinancialParseError(message=e) if isinstance(e, str) else FinancialParseError(**e)
            for e in import_result.get("errors", [])
        ]
        return FinancialUploadResult(
            success=False,
            message="データの保存に失敗しました",
            month=parsed.get("month"),
            errors=errors,
            warnings=parsed.get("warnings", []),
        )

    # 成功
    data_type = "予算" if parsed.get("is_target") else "実績"
    return FinancialUploadResult(
        success=True,
        message=f"財務データ（{data_type}）をインポートしました",
        month=parsed.get("month"),
        data_type=data_type,
        action=import_result.get("action"),
        errors=[],
        warnings=parsed.get("warnings", []),
    )


# =============================================================================
# 製造データExcelアップロード
# =============================================================================

@router.post(
    "/manufacturing",
    response_model=ManufacturingUploadResult,
    summary="製造データExcelをアップロード",
    description="""
    製造データExcelファイルをアップロードして処理する。

    ## Excelフォーマット
    - B1: 対象年月（"2025年11月" 形式）
    - 3行目: ヘッダー（日付, 製造量(バット), 製造量(個), 出勤者数, 1人あたり製造量, 有給取得(時間)）
    - 4行目以降: 日次データ

    ## 処理内容
    1. Excelファイル読み込み
    2. パース・バリデーション
    3. manufacturing_dataテーブルへのUpsert（日付単位）

    ## 対応形式
    .xlsx形式のみ対応
    """,
    responses={
        200: {
            "description": "インポート成功",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "製造データをインポートしました",
                        "month": "2025-11-01",
                        "imported_count": 22,
                        "summary": {
                            "total_batts": 3500,
                            "total_pieces": 210000,
                            "avg_production_per_worker": 12.5,
                            "working_days": 22
                        },
                        "warnings": []
                    }
                }
            }
        },
        400: {
            "description": "ファイル形式エラー"
        },
        422: {
            "description": "バリデーションエラー"
        }
    }
)
async def upload_manufacturing_excel(
    file: UploadFile = File(..., description="アップロードする製造データExcel（.xlsx）"),
    current_user: User = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_admin),
) -> ManufacturingUploadResult:
    """
    製造データExcelをアップロードして処理する

    Args:
        file: アップロードされたExcelファイル
        current_user: 認証されたユーザー
        supabase: Supabase管理者クライアント

    Returns:
        ManufacturingUploadResult: インポート結果
    """
    # ファイル形式チェック
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Excelファイル（.xlsx形式）をアップロードしてください"
        )

    # ファイル読み込み
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ファイルの読み込みに失敗しました: {str(e)}"
        )

    # Excelパース
    parsed = parse_manufacturing_excel(content)

    if not parsed["success"]:
        # パースエラー
        if parsed["errors"]:
            from app.schemas.financial import ManufacturingParseError
            errors = [
                ManufacturingParseError(**e) if isinstance(e, dict) else ManufacturingParseError(message=str(e))
                for e in parsed["errors"]
            ]
            return ManufacturingUploadResult(
                success=False,
                message="データにエラーがあります",
                errors=errors,
                warnings=parsed.get("warnings", []),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Excelファイルのパースに失敗しました"
        )

    # DBインポート
    try:
        import_result = await import_manufacturing_data(supabase, parsed)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"データのインポートに失敗しました: {str(e)}"
        )

    if not import_result["success"]:
        from app.schemas.financial import ManufacturingParseError
        errors = [
            ManufacturingParseError(message=e) if isinstance(e, str) else ManufacturingParseError(**e)
            for e in import_result.get("errors", [])
        ]
        return ManufacturingUploadResult(
            success=False,
            message="データの保存に失敗しました",
            month=parsed.get("month"),
            errors=errors,
            warnings=parsed.get("warnings", []),
        )

    # サマリー作成
    summary = ManufacturingSummary(
        total_batts=parsed["summary"]["total_batts"],
        total_pieces=parsed["summary"]["total_pieces"],
        total_workers=parsed["summary"]["total_workers"],
        avg_production_per_worker=parsed["summary"]["avg_production_per_worker"],
        total_paid_leave_hours=parsed["summary"]["total_paid_leave_hours"],
        working_days=parsed["summary"]["working_days"],
    )

    # 成功
    return ManufacturingUploadResult(
        success=True,
        message="製造データをインポートしました",
        month=parsed.get("month"),
        imported_count=import_result.get("imported_count", 0),
        summary=summary,
        errors=[],
        warnings=parsed.get("warnings", []) + import_result.get("warnings", []),
    )


# =============================================================================
# サンプルデータ取得（開発用）
# =============================================================================

@router.get(
    "/financial/sample",
    summary="財務データサンプル取得",
    description="財務データのテンプレート構造とサンプル値を取得する（開発用）",
    tags=["テスト"],
)
async def get_financial_sample_data():
    """
    財務データのサンプル構造を取得する
    """
    return get_financial_sample()


@router.get(
    "/manufacturing/sample",
    summary="製造データサンプル取得",
    description="製造データのテンプレート構造とサンプル値を取得する（開発用）",
    tags=["テスト"],
)
async def get_manufacturing_sample_data():
    """
    製造データのサンプル構造を取得する
    """
    return get_manufacturing_sample()
