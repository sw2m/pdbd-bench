package main

func limit(p Params) int {
	return max(p.Flows, p.Load+1, p.Idle, p.Churn) + 1
}
