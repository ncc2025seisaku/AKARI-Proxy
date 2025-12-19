---
description: プロジェクトのタスクを洗い出してGitHub Issueを作成するワークフロー
---

# タスク洗い出し・Issue作成ワークフロー

プロジェクトの改善点を洗い出し、GitHub Issueとして登録する手順です。

## 1. 現状調査

以下の領域を調査してタスクを洗い出す：

### 確認項目
- [ ] 既存のオープンIssue（`gh issue list --state open`）
- [ ] CI/CDの状態（`gh run list --limit 10`）
- [ ] ドキュメントの状態（README, CHANGELOG, docs/）
- [ ] テストの網羅性（tests/, integration_test/）
- [ ] 最近の会話履歴から未完了タスク

### 調査対象ディレクトリ
```bash
# プロジェクト構成
ls -la

# CIワークフロー
ls .github/workflows/

# ドキュメント
ls docs/

# テスト
ls tests/
ls akari_flutter/integration_test/  # Flutterの場合
```

## 2. Issue候補の分類

発見した課題を以下の5領域に分類：

| 領域 | プレフィックス | 例 |
|------|---------------|-----|
| 📚 ドキュメント | `docs:` | README整備、CHANGELOG更新 |
| ⚙️ CI/CD | `ci:` | CI安定化、ビルドテスト追加 |
| 🚀 機能改善 | `feat:` / `fix:` / `perf:` | バグ修正、新機能、最適化 |
| 🧪 テスト | `test:` | 統合テスト追加、E2Eテスト |
| 📦 リリース | `release:` | リリース準備、バイナリ公開 |

## 3. 優先度の決定

- **高**: すぐに対応すべき（CI安定化、重要ドキュメント）
- **中**: 近いうちに対応（機能改善、テスト拡充）
- **低**: 余裕があれば対応（最適化、補助ドキュメント）

## 4. Issue作成

// turbo-all

```bash
# 単一Issue作成
gh issue create --title "<prefix>: タイトル" --body "## 概要
説明

## やること
- [ ] タスク1
- [ ] タスク2

## 優先度
高/中/低"
```

### 複数Issue作成の例
```bash
# ドキュメント系
gh issue create --title "docs: README整備" --body "..."
gh issue create --title "docs: CHANGELOG更新" --body "..."

# CI系
gh issue create --title "ci: CIの安定化" --body "..."

# 機能系
gh issue create --title "feat: 新機能名" --body "..."
gh issue create --title "fix: バグ修正" --body "..."
```

## 5. 作成確認

```bash
# オープンIssue一覧
gh issue list --state open

# 特定Issueの詳細
gh issue view <Issue番号>
```

## 6. ラベル付け（オプション）

```bash
# ラベル追加
gh issue edit <Issue番号> --add-label "enhancement"
gh issue edit <Issue番号> --add-label "documentation"
gh issue edit <Issue番号> --add-label "bug"
```

## Tips

- **Issueが多すぎる場合**: 優先度「高」のものだけ先に作成
- **関連Issue**: 本文に`Relates to #XX`を記載
- **マイルストーン**: `gh issue edit --milestone "v1.0.0"`でグループ化
- **アサイン**: `gh issue edit --add-assignee @username`で担当者設定
