---
description: PRを作成してCI修正まで完了するワークフロー
---

# PR作成・CI修正ワークフロー

新機能や修正をPRとして提出し、CIが通過するまでフォローアップする手順です。

## 1. ブランチ作成とコミット

```bash
# 新しいブランチを作成
git checkout -b feature/your-feature-name

# 変更をステージング
git add <files>

# コミット（日本語OK）
git commit -m "feat: 機能の説明"

# プッシュ
git push -u origin feature/your-feature-name
```

## 2. PR作成

```bash
# 日本語タイトル・本文でPR作成
gh pr create --base main --head feature/your-feature-name \
  --title "feat: 機能のタイトル" \
  --body "## 概要
変更内容の説明

## 変更内容
- 変更1
- 変更2

## テスト
- テスト方法"
```

## 3. CI状態確認

```bash
# CIチェックの状態を確認
gh pr checks <PR番号> --json name,state

# 結果例:
# [{"name":"Flutter Unit Tests","state":"SUCCESS"},...]
```

### AI botのレビュー確認

PRが作成されると、AI botが自動的にレビューや変更のまとめを投稿します。

```bash
# PRのコメント・レビューを確認
gh pr view <PR番号> --comments
```

**確認ポイント**:
- AI botからの変更サマリー
- 潜在的な問題の指摘
- 改善提案

問題が指摘された場合は、必要に応じて対応してからマージする。


## 4. CI失敗時の調査

ブラウザでCIログを確認するか、以下のURLを開く：
- `https://github.com/<org>/<repo>/pull/<PR番号>/checks`

### よくあるCI失敗と対処法

| 問題 | 対処法 |
|------|--------|
| Rust未使用警告 | `#[allow(dead_code)]` を追加 |
| PyO3 non_local_definitions | `#![allow(non_local_definitions)]` をlib.rsに追加 |
| Flutter unused import | importを削除 |
| Flutter avoid_print | `analysis_options.yaml`で`avoid_print: false`に設定 |
| サードパーティコードエラー | `analysis_options.yaml`のexcludeに追加 |
| Pythonテストのネットワークエラー | `use_rust_client=False`をテスト設定に追加 |

## 5. 修正・コミット・プッシュ

```bash
# 修正をコミット
git add <files>
git commit -m "fix: CI警告を修正"

# プッシュ（CIが再実行される）
git push
```

## 6. マージ

```bash
# スカッシュマージ（コミットを1つにまとめる）
gh pr merge <PR番号> --squash --delete-branch
```

### CI完了を待たずにマージしてよいケース

以下の条件を満たす場合、全CIの完了を待たずにマージ可能：

| ケース | 理由 |
|--------|------|
| ドキュメント変更のみ | ビルドに影響なし |
| 設定ファイル変更のみ（.gitignore等） | コードに影響なし |
| コメント追加・削除のみ | ロジックに影響なし |
| Rust+Python testsが成功済み | コア機能は検証済み |

**判断基準**: 変更内容がビルドやテスト結果に影響しないことが明らかな場合

## Tips

- **CIが通らない場合**: 問題を特定して修正PRを作成するか、同じブランチに追加コミット
- **日本語タイトル**: `gh pr create`や`gh pr edit`で日本語使用可能
- **ブランチ削除**: `--delete-branch`オプションでマージ後に自動削除

