# ONGOING









\--------------------------------------------------------------------------------------------



##### Prompt 5 — Custom categories and custom accounts from user JSON





You are given the latest ZIP of my Flask Money Manager repo.



Assume Steps 1-4 are already completed:

\- Launcher exists.

\- Multi-user auth and user-specific paths exist.

\- User profile/preferences JSON foundation exists.

\- Profile page exists with theme, language, avatar, and money profile.



Goal of this patch:

Make categories and accounts fully user-customizable from JSON and manageable from the webapp.



Important:

The app currently has hard-coded/default categories in money\_manager/config/categories.py and account logic in money\_manager/config/accounts.py and money\_manager/services/account\_service.py.

Do not break existing transactions.



Implement the following:



1\. Category system

Create or update:

\- money\_manager/services/custom\_category\_service.py

\- money\_manager/config/categories.py if needed

\- transaction forms/templates that show category choices



Desired logic:

effective categories = default app categories + user custom categories - user hidden categories



Per-user file:

data/users/{user\_id}/categories.json



Expected structure:

{

&#x20; "schema\_version": 1,

&#x20; "expense": {

&#x20;   "custom": \[],

&#x20;   "hidden": \[],

&#x20;   "default": "Other"

&#x20; },

&#x20; "income": {

&#x20;   "custom": \[],

&#x20;   "hidden": \[],

&#x20;   "default": "Other"

&#x20; },

&#x20; "investment": {

&#x20;   "custom": \[],

&#x20;   "hidden": \[],

&#x20;   "default": "Other"

&#x20; }

}



Requirements:

\- Existing default categories remain available unless hidden by the user.

\- User can add a new category for expenses, incomes, and investments.

\- User can hide a default category.

\- User can restore hidden categories.

\- User can delete custom categories only if safe:

&#x20; - If existing transactions use that category, do not delete silently.

&#x20; - Either prevent deletion or allow archive/hide.

\- No old transaction should be corrupted if its category is not currently visible.

\- Transaction detail/history should still display old categories.



2\. Category management UI

Add this to the Profile page or a dedicated settings subsection:

\- “Categories”

\- Expense categories

\- Income categories

\- Investment categories

\- Add custom category

\- Hide/show default category

\- Restore default categories



Use existing UI style.

Do not make a huge redesign.



3A. Account system

Move accounts to per-user account config:

data/users/{user\_id}/accounts.json



If Step 2 already copied accounts.json into each user folder, continue from that.



Requirements:

\- User can add/edit/archive accounts from the webapp.

\- Existing account page should use only current user’s accounts.

\- Transaction forms should read account choices from current user’s account config.

\- Support at least:

&#x20; - id

&#x20; - name

&#x20; - type

&#x20; - currency

&#x20; - institution/bank optional

&#x20; - iban optional

&#x20; - initial\_balance optional

&#x20; - is\_active

&#x20; - display\_order

\- Do not break existing transactions that reference older account names.

\- If an account is archived, keep it visible in old transactions but hide it from new transaction dropdowns by default.

\- Preserve current account calculations.



3B. Custom document types and document upload system



Add customizable document types.



Per-user file:

data/users/{user\_id}/document\_types.json



Expected structure:

{

&#x20; "schema\_version": 1,

&#x20; "types": \[

&#x20;   {

&#x20;     "id": "cedolini",

&#x20;     "name": "Cedolini",

&#x20;     "description": "Payslips and salary documents",

&#x20;     "is\_default": true,

&#x20;     "is\_active": true,

&#x20;     "display\_order": 10

&#x20;   },

&#x20;   {

&#x20;     "id": "detrazioni\_fiscali",

&#x20;     "name": "Detrazioni Fiscali",

&#x20;     "description": "Tax deduction documents",

&#x20;     "is\_default": true,

&#x20;     "is\_active": true,

&#x20;     "display\_order": 20

&#x20;   }

&#x20; ]

}



Requirements:

\- The default document types are:

&#x20; - Cedolini

&#x20; - Detrazioni Fiscali

\- User can add custom document types.

\- User can edit custom document types.

\- User can archive/hide document types.

\- User can restore archived document types.

\- If a document already uses a document type, do not delete the type destructively.

\- Old uploaded documents should still show their original document type even if that type is later archived.

\- Do not corrupt existing document records.



Update or create:

\- money\_manager/services/document\_type\_service.py

\- money\_manager/services/document\_service.py if needed

\- money\_manager/repositories/documents.py if present

\- money\_manager/web/routes/support/documents.py or the actual existing documents route

\- money\_manager/web/templates/support/documents.html or the actual existing documents template



Document upload from webpage:

\- The Documents page must allow uploading files from the webapp.

\- Upload form fields:

&#x20; - File

&#x20; - Document type

&#x20; - Title/name

&#x20; - Date

&#x20; - Notes optional

\- Store uploaded files inside:

&#x20; data/users/{user\_id}/documents/

\- Store document metadata in:

&#x20; data/users/{user\_id}/documents/\_metadata.json



Suggested metadata structure:

{

&#x20; "schema\_version": 1,

&#x20; "documents": \[

&#x20;   {

&#x20;     "id": "uuid",

&#x20;     "title": "",

&#x20;     "document\_type\_id": "cedolini",

&#x20;     "document\_type\_name\_snapshot": "Cedolini",

&#x20;     "original\_filename": "",

&#x20;     "stored\_filename": "",

&#x20;     "relative\_path": "",

&#x20;     "mime\_type": "",

&#x20;     "size\_bytes": 0,

&#x20;     "document\_date": "",

&#x20;     "notes": "",

&#x20;     "created\_at": "",

&#x20;     "updated\_at": "",

&#x20;     "is\_archived": false

&#x20;   }

&#x20; ]

}



Security requirements:

\- Never trust uploaded filenames.

\- Sanitize filenames.

\- Generate safe stored filenames.

\- Prevent path traversal.

\- Allow common safe document extensions:

&#x20; - pdf

&#x20; - png

&#x20; - jpg

&#x20; - jpeg

&#x20; - webp

&#x20; - doc

&#x20; - docx

&#x20; - xls

&#x20; - xlsx

&#x20; - csv

\- Reject dangerous extensions such as exe, bat, cmd, ps1, js, vbs.

\- Limit upload file size reasonably.

\- Do not store uploaded documents in public static/.

\- Serve/download documents only through protected Flask routes.

\- Current user can access only their own documents.



Documents page UI:

\- Show uploaded documents in a table/card list.

\- Filters:

&#x20; - document type

&#x20; - date

&#x20; - search by title/filename/notes

\- Actions:

&#x20; - Upload document

&#x20; - Download/view document

&#x20; - Edit metadata

&#x20; - Archive document

&#x20; - Restore archived document

\- Add a small settings area or link to manage document types.



Document type management UI:

\- Can be placed in the existing Documents page or Profile/settings page.

\- User can:

&#x20; - Add type

&#x20; - Rename custom type

&#x20; - Archive/hide type

&#x20; - Restore type

\- Keep Cedolini and Detrazioni Fiscali as default active types.



4\. Add management UI

Either update existing Accounts page or Profile settings:

\- Add account

\- Edit account

\- Archive account

\- Restore archived account

\- Reorder accounts if easy



Prefer updating existing Accounts page if it already exists.



5\. Update forms

Update all relevant forms to use effective user categories/accounts:

\- Add transaction

\- Quick log

\- Internal transfers

\- Investments

\- Pending/recurring if they use categories/accounts

\- Debts/receivables/payables if they use account choices



6\. Validation

\- Category/account names should be sanitized but not overly restrictive.

\- Prevent empty duplicate categories.

\- Prevent duplicate active account IDs.

\- Keep display names user-friendly.



Validation requirements:

\- Run python -m compileall money\_manager.

\- Verify new user has default categories/accounts.

\- Verify adding a custom expense category makes it appear in Add Transaction.

\- Verify hiding a default category removes it from new transaction dropdowns but does not break old transactions.

\- Verify adding/editing/archiving account works.

\- Verify old transactions still display correctly.

\- Verify analytics still group by old and custom categories.

\- Verify multi-user separation: user A categories/accounts do not appear for user B.

\- Do not modify phone-specific UI.

\- Verify Cedolini and Detrazioni Fiscali exist by default for every user.

\- Verify user can add a custom document type.

\- Verify archived document types disappear from new upload dropdowns but old documents still display correctly.

\- Verify uploading a file from the Documents page stores it in data/users/{user\_id}/documents/.

\- Verify document metadata is stored in \_metadata.json.

\- Verify documents are served only through protected routes.

\- Verify user A cannot access user B documents.



Output:

Return the FULL updated repo as a downloadable .zip.

Also summarize:

\- Files added

\- Files modified

\- How effective categories are computed

\- How archived accounts/categories are handled



