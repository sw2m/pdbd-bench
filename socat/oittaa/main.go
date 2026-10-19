// see socat/README.md "Corpus"
package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strconv"
)

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: walker MODULE-DIR")
		os.Exit(2)
	}
	files, err := filepath.Glob(filepath.Join(os.Args[1], "internal", "parse", "*_test.go"))
	if err != nil || len(files) == 0 {
		fmt.Fprintln(os.Stderr, "no parser tests under", os.Args[1])
		os.Exit(2)
	}
	set := token.NewFileSet()
	for _, f := range files {
		file, err := parser.ParseFile(set, f, nil, 0)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		ast.Inspect(file, func(n ast.Node) bool {
			call, ok := n.(*ast.CallExpr)
			if !ok || len(call.Args) == 0 {
				return true
			}
			name := ""
			switch fun := call.Fun.(type) {
			case *ast.Ident:
				name = fun.Name
			case *ast.SelectorExpr:
				name = fun.Sel.Name
			}
			if name != "ParseChannel" && name != "ParseSpec" {
				return true
			}
			lit, ok := call.Args[0].(*ast.BasicLit)
			if !ok || lit.Kind != token.STRING {
				return true
			}
			if s, err := strconv.Unquote(lit.Value); err == nil {
				b, _ := json.Marshal(s)
				fmt.Println(string(b))
			}
			return true
		})
	}
}
