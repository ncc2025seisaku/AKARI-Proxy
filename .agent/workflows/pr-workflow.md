---
description: PRを作成してCI修正まで完了するワークフロー
---

# PRワークフロー

このワークフローはブランチを作成し、PRを作成・レビュー確認・マージまでを行います。

## 1. 現在の変更を確認
```bash
git status
git diff --stat
```

## 2. フィーチャーブランチを作成
```bash
git checkout -b feature/<機能名>
```
ブランチ名は `feature/`, `fix/`, `docs/` などのprefixを使用。

## 3. 変更をコミット
```bash
git add <変更ファイル>
git commit -m "<type>: <説明>

<詳細な説明（任意）>"
```
typeは `feat`, `fix`, `docs`, `refactor`, `test` など。
コミットメッセージは日本語で記述。

## 4. リモートにプッシュ
```bash
git push -u origin <ブランチ名>
```

## 5. PRを作成
```bash
gh pr create --title "<PRタイトル>" --body "<PR説明>" --base develop
```
PR本文には以下を含める:
- 概要
- 変更内容
- テスト結果

## 6. CIチェック状態を確認
```bash
gh pr checks <PR番号>
```
ビルドテストは時間がかかるため、Lint/Analyzeがパスしていれば進んでよい。

## 7. botレビューを確認 ⭐ 重要
```bash
gh pr view <PR番号> --comments
```
AIボットからのコードレビューコメントを確認し、指摘事項があれば対応する。
問題がなければ次のステップへ進む。

## 8. PRをマージ
```bash
gh pr merge <PR番号> --squash --delete-branch
```
Squashマージでコミット履歴をクリーンに保つ。

## 9. ローカルを更新
```bash
git checkout develop
git pull
```

## CI失敗時の対応
1. エラーログを確認: `gh run view <run-id> --log-failed`
2. 修正をコミット・プッシュ
3. CIが再実行されるのを待つ
4. ステップ6から再開
