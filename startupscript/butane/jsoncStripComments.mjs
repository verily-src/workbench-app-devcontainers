#!/usr/bin/env node
import { stripComments } from "jsonc-parser";
import fs from "fs"; 
const jsonc = fs.readFileSync(process.stdin.fd, 'utf-8');
const json = stripComments(jsonc); 
fs.writeFileSync(process.stdout.fd, json); 