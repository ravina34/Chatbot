class AdmissionAgent:
    def get_response(self, query):

        query = query.lower()

        if "eligibility" in query:
            return "Minimum eligibility is 60% in 12th."

        elif "documents" in query:
            return "Documents: 10th Marksheet, 12th Marksheet, Aadhaar, TC"

        elif "last date" in query:
            return "Admission last date is 31 July."

        else:
            return "Please ask only admission related questions."
