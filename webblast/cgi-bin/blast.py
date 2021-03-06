#!/usr/bin/python

# blast.py -- run a blast instance (with dynamic loading of database names)
# via Python

import cgi # for cgi forms
import cgitb # for cgi trace-back
import re # for regular expression parsing
import os # file existence, urandom [sessionIDs]
import base64 # for encoding sessionIDs
import subprocess # for running external programs
import csv # for parsing csv files (e.g. blast output)
import time # for results file cleanup
import tempfile # for blast results
from Bio.Blast import NCBIXML # for XML parsing
from decimal import Decimal # for scientific notation

def printFile(fileName, parameters, printContent):
    if(printContent):
        # HTTP header
        print('Content-type: text/html\n\n')
    if(not(os.path.exists(fileName))):
        print('File does not exist: %s' % fileName);
        return
    readFile = open(fileName, 'r')
    for line in readFile:
        paramMatches = re.findall("%\((.*?)\)", line)
        for param in paramMatches:
            # doing a 'manual' replacement because the usual %(param)
            # notation doesn't seem to work
            if(param in parameters):
                line = line.replace('%(' + param + ')',
                                    parameters[param])
            else:
                line = line.replace('%(' + param + ')', '')
        seenFields = re.findall('<(?:input|textarea|select).*?name="(.*?)"', line)
        for field in seenFields:
            parameters['seenFields'].append(field)
        print(line.rstrip())

def printHiddenValues(lastForm, parameters):
    # make sure runBlast state isn't preserved across multiple submits
    # [don't want it to try running more than once]
    parameters['seenFields'].append('runBlast')
    # add fields from 'addFields' to hidden values
    for field in parameters['addFields']:
        if(not(field in parameters['seenFields']) and
           field in parameters):
            print('<input type="hidden" name="%s" value="%s">' %
                  (field, parameters[field]))
    # add fields from previous form to hidden values
    for field in lastForm:
        if(not(field in parameters['seenFields'])):
            print('<input type="hidden" name="%s" value="%s">' %
                  (field, lastForm.getfirst(field)))


def getBlastDBs(parameters):
    printString = ''
    runArgs = ('blastdbcmd','-list','db','-list_outfmt','%f,%p,%t')
    expectsNucleotide = parameters['program'] in ('blastn', 'tblastn', 'tblastx')
    expectsProtein = parameters['program'] in ('blastp', 'blastx')
    # writeError('program: %s, en: %s, ep: %s' % (parameters['program'], expectsNucleotide, expectsProtein), parameters)
    dbOutFile = subprocess.Popen(args=runArgs, shell=False,
                                  stdout=subprocess.PIPE, cwd='.').stdout
    reader = csv.reader(dbOutFile)
    for row in reader:
        if((len(row) == 3) and not (re.search("\.[0-9]+",row[0]))):
            if((expectsNucleotide and (row[1] == 'Nucleotide')) or
               (expectsProtein and (row[1] == 'Protein'))):
                if(('queryDB' in parameters) and (parameters['queryDB'] == row[0])):
                    printString += '<option value="%s" selected="selected">%s [%s]</option>' % (row[0], row[2], row[1]);
                else:
                    printString += '<option value="%s">%s [%s]</option>' % (row[0], row[2], row[1]);
    return(printString)

def loadForm(lastForm, parameters):
    # retrieves data values from the previous form
    for field in lastForm:
        parameters[field] = lastForm.getfirst(field, '')

def loadDefaults(fileName, parameters):
    # loads default form values from a file
    reader = csv.reader(open(fileName))
    for row in reader:
        if(len(row) == 2):
            parameters[row[0]] = row[1]

def writeError(errorMessage, parameters):
    printFile('templates/header.html', myparams, True)
    print("<h1>Error</h1>")
    print("<p>%s</p>" % errorMessage)
    printHiddenValues(form, myparams)
    printFile('templates/footer.html', myparams, False)
    exit(0)

def runBlast(programName, lastForm, parameters):
    resultStorageName = 'templates/results/resultsFiles.csv';
    allowedPrograms = ('blastn','blastp','blastx','tblastn','tblastx')
    if(not(programName in allowedPrograms)):
        writeError("Unable to run '%s' (not an allowed program)"
                   % programName, parameters)
        return
    resultFile = tempfile.NamedTemporaryFile(delete = False)
    errorFile = tempfile.NamedTemporaryFile(delete = False)
    # print header so that file will be deleted
    resultStorageFile = open(resultStorageName,'ab')
    inputFile = tempfile.NamedTemporaryFile(delete = False)
    if(not(parameters['inputText'].startswith('>'))):
        # no sequence name, so add in a name from the session ID
        inputFile.write("> %s\n" % parameters['sessionID'])
    inputFile.write("%s\n" % parameters['inputText'])
    if(len(parameters['inputFile']) > 0):
        inputFile.write(parameters['inputFile'])
    inputFile.close()
    writer = csv.writer(resultStorageFile)
    writer.writerow( (parameters['sessionID'],resultFile.name,str(time.time())) )
    writer.writerow( (parameters['sessionID']+".err",errorFile.name,str(time.time())) )
    resultStorageFile.close()
    commandLine = list((programName,
                   '-db', parameters['queryDB'],
                   '-query', inputFile.name,
                   '-outfmt', '5'))
    taskName = programName;
    # adjust for short input sequences
    # see http://www.ncbi.nlm.nih.gov/blast/Blast.cgi?CMD=Web&PAGE_TYPE=BlastDocs&DOC_TYPE=FAQ#Short
    if(not('SHORT_QUERY_ADJUST' in parameters) or
       (parameters['SHORT_QUERY_ADJUST'] == 'on')):
        inputTextSequence = re.sub('^>.*?$','',parameters['inputText']);
        if(len(inputTextSequence) < 30):
            taskName += '-short'
    if((programName == 'blastn') or (programName == 'blastp')):
        commandLine.extend(('-task', taskName)) # default blastn is megablast
    if(('EXPECT' in parameters) and (parameters['EXPECT'] != '')):
        commandLine.extend(('-evalue', parameters['EXPECT']))
    if(('MAX_NUM_SEQ' in parameters) and (parameters['MAX_NUM_SEQ'] != '')):
        commandLine.extend(('-max_target_seqs', parameters['MAX_NUM_SEQ']))
    if((programName == 'blastn')):
        if(('WORD_SIZE' in parameters) and (parameters['WORD_SIZE'] != '')):
            commandLine.extend(('-word_size', parameters['WORD_SIZE']))
    if(('TASK' in parameters) and (parameters['TASK'] != '')):
        commandLine.extend(('-task', parameters['TASK']))
    parameters['blastCommand'] = str(commandLine)
    runProcess = subprocess.Popen(commandLine, stdout = resultFile, stderr = errorFile)
    # allow a bit of time for BLAST to start up [and give the user
    # some illusion that things aren't happening in the background]
    time.sleep(1)
    # remove the input file (on unix it will only be deleted when
    # the subprocess is finished)
    os.unlink(inputFile.name)
    parameters['resultsExist'] = 'True'

def getSequences(parameters, searchDict):
    lookups = list(searchDict.keys())
    searchFileName = ""
    with tempfile.NamedTemporaryFile(delete=False) as searchFile:
        searchFileName = searchFile.name
        for searchCode in lookups:
            searchFile.write('%s\n' % searchCode)
    commandLine = list(('blastdbcmd',
                        '-db', parameters['queryDB'],
                        '-entry_batch', searchFileName,
                        '-outfmt', '%s'))
    seqs = list()
    with tempfile.TemporaryFile() as outFile:
        runProcess = subprocess.Popen(commandLine, stdout = outFile)
        runProcess.wait()
        outFile.seek(0)
        for line in outFile:
           seqs.append(line.rstrip())
    for pos in xrange(len(seqs)):
        searchDict[lookups[pos]] = seqs[pos]
    os.unlink(searchFileName)

def cleanUpResultsFiles(parameters):
    # NOTE: this method deletes files. While attempts are made to make
    # sure only appropriate files are deleted, it is not advisable to
    # trust this completely (i.e. don't run the web server as a user
    # that has access to critical system files)
    resultStorageName = 'templates/results/resultsFiles.csv';
    if(not(os.path.exists(resultStorageName))):
        # no file exists, so no results files exist
        return
    filesToAdd = list()
    reader = csv.reader(open(resultStorageName))
    for row in reader:
        sessionID = row[0]
        resultFileName = row[1]
        creationTime = float(row[2])
        currentTime = time.time()
        removed = False
        # delete results 24h after creation
        if(currentTime - creationTime > 60 * 60 * 24):
            # read first line to make sure it really is a results file
            # [the program shouldn't delete files that aren't results files]
            if(os.path.exists(resultFileName)):
                resultFile = open(resultFileName, 'r')
                isResultFile = False
                if(os.path.getsize(resultFileName) > 0):
                    line1 = resultFile.readline()
                    if(('BLAST' in line1) or ('USAGE' in line1) or
                       ('Command line argument error:' in line1) or
                       ('Error: NCBI' in line1) or ('CFastaReader' in line1)):
                        isResultFile = True
                    else:
                        line2 = resultFile.readline()
                        resultFile.close()
                        if('NCBI BlastOutput' in line2):
                            isResultFile = True
                else:
                    # empty files are assumed to be empty results files
                    isResultFile = True
                if(not(isResultFile)):
                    if(not 'errors' in parameters):
                        parameters['errors'] = ''
                    parameters['errors'] += 'File \'%s\' does not look like a results file\n' % (
                        resultFileName)
                else:
                    try:
                        os.remove(resultFileName)
                        removed = True
                    except OSError:
                        if(not 'errors' in parameters):
                            parameters['errors'] = ''
                        parameters['errors'] += 'File \'%s\' cannot be deleted by %s' % (
                            resultFileName, os.getuid())
            else:
                # File has already been removed, so it shouldn't be in the list
                removed = True
        if(not(removed)):
            filesToAdd.append(row)
    # re-write files that have not been deleted back to file
    resultStorageFile = open(resultStorageName,'wb')
    writer = csv.writer(resultStorageFile)
    writer.writerows(filesToAdd)
    resultStorageFile.close()

def getResults(parameters):
    resultStorageName = 'templates/results/resultsFiles.csv';
    mostRecentFileName = None
    mostRecentTime = 0
    mostRecentErrorFileName = None
    mostRecentErrorTime = 0
    formattedPreResult = ''
    formattedSummaryResult = ''
    formattedFullResult = ''
    context = 0
    # sort out GBrowse pattern replacements
    gbrowsePatterns = dict()
    if('gbrowse_patterns' in parameters):
        patternList = parameters['gbrowse_patterns'].split(';');
        for pattern in patternList:
            components = pattern.split(':',1)
            gbrowsePatterns[components[0]] = components[1]
    # set up additional context
    if(('CONTEXT' in parameters) and
       (parameters['CONTEXT'] != '')):
        context = int(parameters['CONTEXT'])
    # find location of results files and error output
    reader = csv.reader(open(resultStorageName))
    for row in reader:
        sessionID = row[0]
        resultFileName = row[1]
        creationTime = float(row[2])
        if((sessionID == parameters['sessionID']) and
           (creationTime >= mostRecentTime)):
            mostRecentFileName = resultFileName
            mostRecentTime = creationTime
        if((sessionID == parameters['sessionID']+".err") and
           (creationTime >= mostRecentErrorTime)):
            mostRecentErrorFileName = resultFileName
            mostRecentErrorTime = creationTime
    resultsFound = False
    if(mostRecentFileName != None):
        if((mostRecentErrorFileName != None) and (os.path.getsize(mostRecentErrorFileName) > 0)):
            f = open(mostRecentErrorFileName, 'r')
            errorStr = "<pre>"
            for line in f:
                errorStr += line
            errorStr += "</pre>"
            writeError(errorStr, parameters)
            return
        if(os.path.getsize(mostRecentFileName) == 0):
            return('The results file is empty. Have a sip of your favourite beverage then click "Results" again.')
        resultFile = open(mostRecentFileName, 'r')
        blast_records = NCBIXML.parse(resultFile)
        formattedPreResult += ('<p>Reference Database: %s</p>\n'
                               % parameters['queryDB'])
        formattedPreResult += ('<p>BLAST Run started: %s</p>\n'
                               % time.strftime('%Y-%b-%d %H:%M:%S',
                                               time.localtime(mostRecentTime)))
        formattedFullResult += '<h2>Match Details</h2>'
        formattedFullResult += '<pre>\n'
        numAlignments = 0
        queries = set()
        summaryTable = list()
        origSeq = dict()
        translatedQuery = (parameters['program'] == 'blastx')
        translatedSub = ((parameters['program'] == 'tblastn') or (parameters['program'] == 'tblastx'))
        for blast_record in blast_records:
            for alignment in blast_record.alignments:
                for hsp in alignment.hsps:
                    resultsFound = True
                    query = blast_record.query
                    subject = alignment.hit_def
                    if('hit_id' in vars(alignment) and not ('BL_ORD_ID' in alignment.hit_id)):
                        subject = alignment.hit_id
                    if(" " in query):
                        query = query[0:query.find(" ")];
                    if(" " in subject):
                        subject = subject[0:subject.find(" ")];
                    identity = float(hsp.identities) / (hsp.align_length) * 100
                    coverage = float(abs(hsp.query_end - hsp.query_start)+1) / blast_record.query_length * 100
                    subjCoverage = float(abs(hsp.sbjct_end - hsp.sbjct_start)+1) / alignment.length * 100
                    # place appropriate hyperlinks into subject names
                    for subPattern in gbrowsePatterns:
                        if(subPattern in subject):
                            subject = (
                                gbrowsePatterns[subPattern] %
                                (subject,
                                 min(hsp.sbjct_start, hsp.sbjct_end),
                                 max(hsp.sbjct_start, hsp.sbjct_end),
                                 subject,
                                 min(hsp.sbjct_start, hsp.sbjct_end),
                                 max(hsp.sbjct_start, hsp.sbjct_end),
                                 subject))
                    alignmentText = '<a name="%d" href="#summary">**** Alignment %d ****</a>\n' % (
                        numAlignments, numAlignments)
                    alignmentText += 'query: %s\n' % query
                    alignmentText += 'query length: %s\n' % blast_record.query_length
                    alignmentText += 'subject: %s\n' % subject
                    alignmentText += 'subject length: %s\n' % alignment.length
                    alignmentText += 'align length: %s\n' % hsp.align_length
                    if('frame' in vars(hsp)):
                        alignmentText += 'frame: (%d,%d)\n' % hsp.frame
                    alignmentText += 'score: %s\n' % hsp.score
                    alignmentText += 'bits: %s\n' % hsp.bits
                    alignmentText += 'identity: %0.2f%%\n' % identity
                    alignmentText += 'query coverage: %0.2f%%\n' % coverage
                    alignmentText += 'subject coverage: %0.2f%%\n' % subjCoverage
                    alignmentText += 'e value: %g\n' % hsp.expect
                    #alignmentText += '\n%s\n\n' % vars(hsp)
                    querySpos = oldQPos = queryPos = hsp.query_start
                    sbjctSpos = oldSPos = sbjctPos = hsp.sbjct_start
                    alignSpos = alignPos = 0
                    queryDir =  1 if (hsp.query_start < hsp.query_end) else -1
                    sbjctDir = 1 if (hsp.sbjct_start < hsp.sbjct_end) else -1
                    incQuery = False
                    incSbjct = False
                    incStepSbjct = 1
                    if(translatedSub):
                        incStepSbjct = 3
                    for hsp.char in hsp.match:
                        if(hsp.query[alignPos] != '-'):
                            oldQPos = queryPos
                            if(not incQuery):
                                querySpos = queryPos
                            incQuery = True
                            queryPos += queryDir
                        if(hsp.sbjct[alignPos] != '-'):
                            oldSPos = sbjctPos
                            if(not incSbjct):
                                sbjctSpos = sbjctPos
                            incSbjct = True
                            sbjctPos += sbjctDir
                        alignPos += 1
                        if((alignPos % 100 == 0) or (alignPos >= len(hsp.match))):
                            if('frame' in vars(hsp) and (hsp.frame[1] < 0)):
                                adjSSPos = hsp.sbjct_end - (sbjctSpos - hsp.sbjct_start) * incStepSbjct
                                adjSEPos = hsp.sbjct_end - (oldSPos - hsp.sbjct_start) * incStepSbjct + (incStepSbjct-1)
                            else:
                                adjSSPos = hsp.sbjct_start + (sbjctSpos - hsp.sbjct_start) * incStepSbjct
                                adjSEPos = hsp.sbjct_start + (oldSPos - hsp.sbjct_start) * incStepSbjct + (incStepSbjct-1)
                            alignmentText += '\n'
                            alignmentText += 'Query %9d %s %-9d\n' % (
                                querySpos, hsp.query[alignSpos:alignPos], oldQPos)
                            alignmentText += '      %9s %s\n' % ('', hsp.match[alignSpos:alignPos])
                            alignmentText += 'Sbjct %9s %s %-9d\n' % (
                                adjSSPos, hsp.sbjct[alignSpos:alignPos], adjSEPos)
                            incQuery = False
                            incSbjct = False
                            alignSpos = alignPos
                    formattedFullResult += alignmentText + '\n'
                    gaplessQuery = hsp.query.replace("-","")
                    gaplessSbjct = hsp.sbjct.replace("-","")
                    formattedFullResult += '** Gapless Query Match Subsequence **\n'
                    formattedFullResult += '>%s [%d..%d]\n' % (query, hsp.query_start, hsp.query_end)
                    for spos in xrange(0,len(gaplessQuery),70):
                        formattedFullResult += gaplessQuery[spos:spos+70] + '\n'
                    appendString = (' (translated)' if translatedSub else '')
                    if((context > 0) and not translatedSub):
                        appendString += ' (%d context)' % context
                    formattedFullResult += '\n** Gapless Subject Match Subsequence%s **\n' % appendString
                    if((context > 0) and not translatedSub):
                        matchStart = max(1,hsp.sbjct_start-context)
                        matchEnd = hsp.sbjct_end+context
                        if(matchEnd < matchStart):
                            matchStart = max(1,hsp.sbjct_end-context)
                            matchEnd = hsp.sbjct_start+context
                        matchCode = '%s %d-%d' % (
                            alignment.hit_id, matchStart, matchEnd)
                        formattedFullResult += '%%SEQ(%s)\n' % matchCode
                        origSeq[matchCode] = ""
                    else:
                        formattedFullResult += '>%s [%d..%d%s%s]\n' % (
                            subject, hsp.sbjct_start, hsp.sbjct_end,
                            ',translated' if translatedSub else '',
                            ',RC' if ('frame' in vars(hsp) and (hsp.frame[1] < 0)) else '')
                        for spos in xrange(0,len(gaplessSbjct),70):
                            formattedFullResult += gaplessSbjct[spos:spos+70] + '\n'
                    if(translatedSub and ('hit_id' in vars(alignment))):
                        matchStart = max(1,hsp.sbjct_start-context)
                        matchEnd = hsp.sbjct_end+context
                        if(matchEnd < matchStart):
                            matchStart = max(1,hsp.sbjct_end-context)
                            matchEnd = hsp.sbjct_start+context
                        matchCode = '%s %d-%d' % (
                            alignment.hit_id, matchStart, matchEnd)
                        formattedFullResult += '\n** Gapless Subject Match Subsequence%s **\n' % (
                            (' (%d context)' % context) if (context > 0) else '')
                        formattedFullResult += '%%SEQ(%s)\n' % matchCode
                        origSeq[matchCode] = ""
                    formattedFullResult += '\n'
                    queries.add(blast_record.query)
                    summaryTable.append((query, subject, hsp.score,
                        coverage, identity, hsp.expect))
                    numAlignments += 1
        if(translatedSub or (context > 0)):
            getSequences(parameters, origSeq)
            for (key, value) in origSeq.items():
                keyAnnot = '%s]' % key.replace("-","..").replace(" "," [")
                seqStr = ''
                for spos in xrange(0,len(value),70):
                    seqStr += value[spos:spos+70] + '\n'
                formattedFullResult = formattedFullResult.replace('%%SEQ(%s)' % key,'>%s\n%s' % (keyAnnot, seqStr))
        formattedFullResult += '</pre>\n'
        formattedPreResult += ('<p>Number of alignments: %d</p>\n'
                               % numAlignments)
        formattedSummaryResult += '<h2><a name="summary"></a>Summary</h2>\n'
        formattedSummaryResult += '<table class="sortable">\n'
        formattedSummaryResult += ('<thead>\n' +
                                   '  <tr>' +
                                   '<th>Alignment</th>' +
                                   '<th>Query</th>' +
                                   '<th>Subject</th>' +
                                   '<th>Bitscore</th>' +
                                   '<th>Coverage %</th>' +
                                   '<th>Identity %</th>' +
                                   '<th>E value</th>' +
                                   '</tr>\n' +
                                   '</thead>\n')
        formattedSummaryResult += '<tbody>\n'
        for alignment in range(numAlignments):
            formattedSummaryResult += (('  <tr><td><a href="#%d">%d</a></td><td>%s</td><td>%s</td>' +
                                        '<td>%0.2f</td><td>%0.2f</td><td>%0.2f</td><td>%5g</td></tr>\n') % (
                    alignment,
                    alignment,
                    (summaryTable[alignment])[0],
                    (summaryTable[alignment])[1],
                    (summaryTable[alignment])[2],
                    (summaryTable[alignment])[3],
                    (summaryTable[alignment])[4],
                    (summaryTable[alignment])[5]))
        formattedSummaryResult += '</tbody>\n'
        formattedSummaryResult += '</table>\n'
    if(resultsFound):
        return(formattedPreResult + formattedSummaryResult + formattedFullResult)
    else:
        return('No hits were found')

### Begin Actual Program ###

#cgitb.enable() # make errors visible on web pages

form = cgi.FieldStorage()   # FieldStorage object to
                            # hold the form data
myparams = {
    "class_query"  : "taboff",
    "class_params" : "taboff",
    "class_results": "taboff",
    "seenFields"   : list(),
    "addFields"    : ('resultsExist','sessionID','blastCommand'),
    }

#blastn -db db/3alln_smed -query /tmp/tmpGFk3hs -outfmt 5 -task blastn -evalue 10 -max_target_seqs 100 -word_size 11

currentProgram = form.getfirst("selectProgram","blastn")
currentTab = form.getfirst("selectTab","query")

# get local site defaults
loadDefaults('templates/site_defaults.csv', myparams)
# get default values for this program
loadDefaults('templates/%s_defaults.csv' % currentProgram, myparams)
# overwrite default values with previous form values
loadForm(form, myparams)

# add sessionID if it doesn't already exist
if(not('sessionID' in myparams)):
    myparams['sessionID'] = base64.b64encode(os.urandom(16))

myparams['program'] = currentProgram
# activate current tab
myparams['class_' + currentTab] = "tabon"

if(myparams['program'] in ('blastn', 'blastx', 'tblastx')):
    myparams['inputType'] = 'nucleotide';
if(myparams['program'] in ('blastp', 'tblastn')):
    myparams['inputType'] = 'protein';

myparams['databases'] = getBlastDBs(myparams)
myparams['request_uri'] = os.environ['REQUEST_URI']

# remove stale results files
cleanUpResultsFiles(myparams)

# run BLAST (if requested)
if(form.getfirst("runBlast","") == "BLAST"):
    runBlast(currentProgram, form, myparams)

if((not('resultsExist' in myparams)) or (myparams['resultsExist'] != 'True')):
    myparams['class_results'] += " tabdisabled"
else:
    # retrieve result file, and display on tab (if tab is visible)
    if(currentTab == 'results'):
        myparams['results'] = getResults(myparams)

printFile('templates/header.html', myparams, True)
printFile('templates/%s_%s.html' % (currentProgram, currentTab),
          myparams, False)
if('errors' in myparams):
    print('<h3>Errors:</h3><pre>%s</pre>' % myparams['errors']);
printHiddenValues(form, myparams)
printFile('templates/footer.html', myparams, False)
