import { Body, Controller, Get, Post } from '@nestjs/common';
import { AppService } from './app.service';

@Controller()
export class AppController {
  constructor(private readonly appService: AppService) {}

  @Get('health')
  health() {
    return { status: 'ok', service: 'payout-service' };
  }

  @Post('payout')
  async payout(@Body() body: any) {
    return this.appService.publishPayout(body);
  }

  @Post('ach-return')
  async achReturn(@Body() body: any) {
    return this.appService.publishAchReturn(body);
  }

  @Post('noc')
  async noc(@Body() body: any) {
    return this.appService.publishNoc(body);
  }
}
