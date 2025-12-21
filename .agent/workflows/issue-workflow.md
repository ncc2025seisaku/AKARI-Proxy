---
description: プロジェクトのタスクを洗い出してGitHub Issueを作成するワークフロー
---

# Issueワークフロー

プロジェクトのTODOや改善点をGitHub Issueとして登録するワークフローです。

## 1. 現在のissue一覧を確認
```bash
gh issue list --state open
```

## 2. コードベースを分析
プロジェクトの構造、TODOコメント、既存の問題点を調査する。

```bash
# TODOコメントを検索
grep -r "TODO" --include="*.dart" --include="*.py" --include="*.rs" .

# FIXMEコメントを検索
grep -r "FIXME" --include="*.dart" --include="*.py" --include="*.rs" .
```

## 3. Issueを作成
```bash
gh issue create --title "<タイトル>" --body "<説明>" --label "<ラベル>"
```

ラベルは以下から選択:
- `bug`: バグ修正
- `enhancement`: 機能追加・改善
- `documentation`: ドキュメント
- `refactor`: リファクタリング
- `test`: テスト追加

## 4. Issue作成のベストプラクティス
- タイトルは簡潔かつ明確に
- 本文には背景・目的・期待される結果を記載
- 関連ファイルや行番号があればリンクを含める
- 優先度が分かるようにラベルを付ける
