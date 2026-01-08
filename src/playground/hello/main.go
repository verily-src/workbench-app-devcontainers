package main

import (
	"fmt"
	"log"
	"net/http"
)

func helloHandler(w http.ResponseWriter, r *http.Request) {
	// Write the response body
	fmt.Fprintf(w, "Hello, World from app!")
}

func main() {
	// Register the handler function for the "/" path
	http.HandleFunc("/", helloHandler)

	log.Printf("Server starting on port 8080...")
	if err := http.ListenAndServe(":8080", nil); err != nil {
		log.Fatal(err)
	}
}
