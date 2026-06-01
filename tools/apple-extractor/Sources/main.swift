import Foundation
import FoundationModels
import PDFKit

@main
struct AppleExtractor {
    static func main() async {
        guard CommandLine.arguments.count > 1 else {
            printError("Usage: apple-extractor <file-path> [context]")
            exit(1)
        }

        let filePath = CommandLine.arguments[1]
        let extraContext = CommandLine.arguments.count > 2
            ? CommandLine.arguments.dropFirst(2).joined(separator: " ")
            : ""

        // Extract text from the document
        let documentText = readFileText(path: filePath)

        // Build full context for the model
        var parts: [String] = []
        if !extraContext.isEmpty {
            parts.append(extraContext)
        }
        parts.append("Filename: \((filePath as NSString).lastPathComponent)")
        if !documentText.isEmpty {
            parts.append("Document content:\n\(String(documentText.prefix(4000)))")
        }

        let text = parts.joined(separator: "\n")

        guard !text.isEmpty else {
            printJSON(vendor: nil, date: nil, confidence: 0)
            exit(0)
        }

        let prompt = """
        Extract invoice metadata from the following. Return JSON only.

        Rules:
        - "vendor": If VENDOR_NAME is provided above, you MUST use it exactly as the vendor value. Do not use any other name from the document.
        - "date": the invoice date in YYYY-MM-DD format. Look for invoice date, billing date, or document date.
        - "confidence": 0.0 to 1.0

        Output format: {"vendor": "...", "date": "YYYY-MM-DD", "confidence": 0.XX}
        Use null for unknown fields.

        \(text)
        """

        do {
            let session = LanguageModelSession()
            let response = try await session.respond(to: prompt)
            let raw = response.content

            if let jsonData = extractJSON(from: raw) {
                let output = try JSONSerialization.data(withJSONObject: jsonData, options: [])
                print(String(data: output, encoding: .utf8) ?? "{}")
            } else {
                printJSON(vendor: nil, date: nil, confidence: 0)
            }
        } catch {
            printError("Model error: \(error.localizedDescription)")
            printJSON(vendor: nil, date: nil, confidence: 0)
        }
    }

    static func readFileText(path: String) -> String {
        let url = URL(fileURLWithPath: path)
        let ext = url.pathExtension.lowercased()

        if ext == "pdf" {
            // Use PDFKit for proper text extraction
            if let pdfDocument = PDFDocument(url: url) {
                var pages: [String] = []
                for i in 0..<pdfDocument.pageCount {
                    if let page = pdfDocument.page(at: i),
                       let text = page.string {
                        pages.append(text)
                    }
                }
                let result = pages.joined(separator: "\n")
                if !result.isEmpty { return result }
            }
            return ""
        }

        // Plain text / other
        return (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""
    }

    static func extractJSON(from text: String) -> [String: Any]? {
        // Find JSON object in response
        guard let start = text.firstIndex(of: "{"),
              let end = text.lastIndex(of: "}") else {
            return nil
        }
        let jsonStr = String(text[start...end])
        guard let data = jsonStr.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return obj
    }

    static func printJSON(vendor: String?, date: String?, confidence: Double) {
        var dict: [String: Any] = ["confidence": confidence]
        dict["vendor"] = vendor ?? NSNull()
        dict["date"] = date ?? NSNull()
        if let data = try? JSONSerialization.data(withJSONObject: dict, options: []),
           let str = String(data: data, encoding: .utf8) {
            print(str)
        } else {
            print(#"{"vendor":null,"date":null,"confidence":0}"#)
        }
    }

    static func printError(_ msg: String) {
        FileHandle.standardError.write(Data((msg + "\n").utf8))
    }
}
