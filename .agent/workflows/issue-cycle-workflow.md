---
description: Issue洗い出し→優先度分析→PR作成→マージの一連のサイクルを回すマスターワークフロー
---

# Issue Cycleワークフロー

Issue管理からPRマージまでの一連のサイクルを回すマスターワークフローです。

## フェーズ1: Issue洗い出し
`/issue-workflow` を実行してタスクをIssue化する。

## フェーズ2: 優先度分析
`/issue-priority-workflow` を実行して着手すべきIssueを選出する。

## フェーズ3: 実装
1. 選出したIssueの内容を確認
2. 実装を行う
3. ローカルでテスト・動作確認

## フェーズ4: PR作成・マージ
`/pr-workflow` を実行してPRを作成・マージする。

## フェーズ5: Issueクローズ
```bash
gh issue close <issue番号> --comment "PR #<PR番号> で対応完了"
```

## サイクルの繰り返し
フェーズ2から再開し、残りのIssueを処理する。
