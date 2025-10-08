// ฟังก์ชันที่ทำงานเมื่อเปิดไฟล์
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('บอทจัดเวร')
    .addItem('1. จัดตารางเวร', 'generateRoster')
    .addSeparator()
    .addItem('2. สร้างสรุปรายงาน', 'generateSummaryReport')
    .addToUi();
}

/**
 * ฟังก์ชันหลักในการจัดตารางเวร
 */
function generateRoster() {
  const ui = SpreadsheetApp.getUi();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // --- 1. อ่านค่าจากการตั้งค่า ---
  const settingsSheet = ss.getSheetByName('ตั้งค่า');
  const settings = settingsSheet.getRange('A2:B6').getValues().reduce((obj, row) => {
    obj[row[0]] = row[1];
    return obj;
  }, {});

  const startTimeStr = settings['เวลาเริ่มเวร (HH:mm)'];
  const endTimeStr = settings['เวลาสิ้นสุดเวร (HH:mm)'];
  const numShifts = parseInt(settings['จำนวนผลัด'], 10);

  // --- 2. ดึงรายชื่อคนที่ "พร้อมเข้าเวร" ---
  const nameSheet = ss.getSheetByName('รายชื่อ');
  const allPersonnel = nameSheet.getRange(2, 1, nameSheet.getLastRow() - 1, 2).getValues();
  const availablePersonnel = allPersonnel
    .filter(person => person[1] === '') // กรองเอาเฉพาะคนที่คอลัมน์ 'สถานะ' ว่าง
    .map(person => person[0]); // เอามาแค่ชื่อ

  if (availablePersonnel.length === 0) {
    ui.alert('ไม่พบรายชื่อผู้ที่พร้อมปฏิบัติหน้าที่!');
    return;
  }

  // --- 3. สุ่มรายชื่อ ---
  for (let i = availablePersonnel.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [availablePersonnel[i], availablePersonnel[j]] = [availablePersonnel[j], availablePersonnel[i]];
  }

  // --- 4. คำนวณช่วงเวลาของแต่ละผลัด ---
  const startDate = new Date();
  const [startHour, startMinute] = startTimeStr.split(':');
  startDate.setHours(startHour, startMinute, 0, 0);

  const endDate = new Date();
  const [endHour, endMinute] = endTimeStr.split(':');
  endDate.setHours(endHour, endMinute, 0, 0);

  // กรณีข้ามวัน (เช่น 18:00 - 06:00)
  if (endDate < startDate) {
    endDate.setDate(endDate.getDate() + 1);
  }

  const totalDurationMinutes = (endDate.getTime() - startDate.getTime()) / 60000;
  const shiftDurationMinutes = Math.floor(totalDurationMinutes / numShifts);

  const timeSlots = [];
  let currentShiftTime = new Date(startDate.getTime());

  for (let i = 0; i < numShifts; i++) {
    const shiftStartTime = new Date(currentShiftTime.getTime());
    const shiftEndTime = new Date(shiftStartTime.getTime() + shiftDurationMinutes * 60000);
    
    const formatTime = (date) => Utilities.formatDate(date, "GMT+7", "HH:mm");
    
    // สำหรับผลัดสุดท้าย ให้จบที่เวลาสิ้นสุดเวรพอดี
    if (i === numShifts - 1) {
       timeSlots.push(`${formatTime(shiftStartTime)} - ${formatTime(endDate)}`);
    } else {
       timeSlots.push(`${formatTime(shiftStartTime)} - ${formatTime(shiftEndTime)}`);
    }
    currentShiftTime = shiftEndTime;
  }
  
  // --- 5. จัดคนลงตารางและบันทึกผล ---
  const rosterSheet = ss.getSheetByName('ตารางเวร');
  rosterSheet.clearContents(); // ล้างข้อมูลเก่า
  rosterSheet.getRange('A1:C1').setValues([['ผลัดที่', 'เวลา', 'ชื่อ - สกุล']]).setFontWeight('bold');
  
  const rosterData = [];
  for (let i = 0; i < numShifts; i++) {
    const shiftNumber = i + 1;
    const time = timeSlots[i];
    const person = availablePersonnel[i % availablePersonnel.length]; // ใช้ % เพื่อวนรายชื่อ
    rosterData.push([shiftNumber, time, person]);
  }
  
  rosterSheet.getRange(2, 1, rosterData.length, 3).setValues(rosterData);
  rosterSheet.autoResizeColumns(1, 3);

  ui.alert('จัดตารางเวรเรียบร้อยแล้ว!');
}


/**
 * ฟังก์ชันสร้างสรุปรายงานเป็นข้อความ
 */
function generateSummaryReport() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // --- อ่านข้อมูลจากการตั้งค่า ---
  const settingsSheet = ss.getSheetByName('ตั้งค่า');
  const dutyDate = settingsSheet.getRange('B2').getValue();
  const dutyDateFormatted = Utilities.formatDate(new Date(dutyDate), "GMT+7", "d MMMM yyyy");
  const recipient = settingsSheet.getRange('B6').getValue();

  // --- อ่านข้อมูลผู้ที่ลา/งดปฏิบัติหน้าที่ ---
  const nameSheet = ss.getSheetByName('รายชื่อ');
  const allPersonnel = nameSheet.getRange(2, 1, nameSheet.getLastRow() - 1, 2).getValues();
  const onLeavePersonnel = allPersonnel.filter(person => person[1] !== '');

  // --- อ่านข้อมูลตารางเวรที่จัดไว้แล้ว ---
  const rosterSheet = ss.getSheetByName('ตารางเวร');
  const rosterData = rosterSheet.getRange(2, 1, rosterSheet.getLastRow() - 1, 3).getValues();
  const totalOnDuty = rosterData.length;

  // --- สร้างข้อความรายงาน ---
  let report = `**เรื่อง:** สรุปเวรประจำวันและสถานะกำลังพล ประจำวันที่ ${dutyDateFormatted}\n`;
  report += `**เรียน:** ${recipient}\n`;
  report += `**วันที่:** ${dutyDateFormatted}\n\n`;
  report += `เรียน ${recipient}\n\n`;
  report += `ขอรายงานสรุปเวรประจำวันและสถานะกำลังพล ประจำวันที่ ${dutyDateFormatted} ดังนี้\n\n`;
  
  report += `**1. สถานะกำลังพล:**\n`;
  onLeavePersonnel.forEach(person => {
    report += `* ${person[0]} (${person[1]})\n`;
  });
  if (onLeavePersonnel.length === 0) {
    report += `- ไม่มีกำลังพลลา\n`;
  }
  report += `ดังนั้น จึงมีกำลังพลพร้อมปฏิบัติหน้าที่ในวันนี้ จำนวน ${totalOnDuty} นาย\n\n`;

  report += `**2. ตารางเวรประจำวัน:**\n`;
  rosterData.forEach(row => {
    // row[0] = ผลัดที่, row[1] = เวลา, row[2] = ชื่อ
    report += `* ผลัดที่ ${row[0]} (${row[1]}) โดย ${row[2]}\n`;
  });
  
  report += `\nจึงเรียนมาเพื่อโปรดทราบ\n\n`;
  report += `ขอแสดงความนับถือ`;

  // --- แสดงผลใน Dialog Box ---
  const htmlOutput = HtmlService.createHtmlOutput(`<pre style="font-family: Arial, sans-serif; white-space: pre-wrap;">${report}</pre>`)
      .setWidth(600)
      .setHeight(400);
  SpreadsheetApp.getUi().showModalDialog(htmlOutput, 'สรุปเวรประจำวัน');
}
